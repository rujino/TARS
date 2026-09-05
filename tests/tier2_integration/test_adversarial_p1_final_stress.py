"""Tier 2 Integration & Adversarial Empirical Stress Test Suite (Milestones 3, 4, 5).

Empirical verification of:
1. REL-03: MCP exponential backoff under flapping network (502/503/504) and hard 10s execution timeout under simulated hang.
2. REL-04: Greeting service timeout: simulate slow LLM taking > 3.0s; verify immediate fallback greeting in < 1ms benchmark.
3. REL-05: Topic shift detection with 2.0s cloud latency budget vs legacy 0.5s timeout.
4. SEC-01: CORS attacks with illegal origins, subdomain spoofing, and credentialed preflights.
5. ASY-06: Burst extractions (30 concurrent calls); verify peak concurrency strictly <= 10 under normal and chaos conditions.
6. OBS-03 & OBS-04: Readiness probe returning 200 under healthy DB/disk, and 503 under severed DB / read-only disk;
   Prometheus /metrics incrementing counters, excluding itself, and reflecting circuit breaker gauge transitions.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from tars.adapters.base import BaseLLMAdapter
from tars.adapters.router import CircuitState, LLMCircuitBreaker
from tars.api.app import create_app
from tars.api.schemas.chat import GreetingResponse
from tars.core.session.detector import TopicShiftDetector
from tars.db.models import User
from tars.services.agent_chat import (
    execute_background_knowledge_extraction,
    get_extraction_semaphore,
)
from tars.services.greeting import ProactiveGreetingService
from tars.storage.manager import FileStorageManager
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import MCPServerConfig, MCPToolMeta, MCPTransportType

# ============================================================================
# Part 1: REL-03 MCP Retry Backoff & Timeout Guard
# ============================================================================


class TestMCPRetryAndTimeoutStress:
    """Empirical stress tests for MCP client retry backoff and execution timeout guard."""

    @pytest.mark.asyncio
    async def test_mcp_flapping_network_recovery_502_503_200(self) -> None:
        """Verify MCP client transparently recovers across flapping 502 -> 503 -> 200 sequence."""
        config = MCPServerConfig(
            name="flapping_service",
            transport=MCPTransportType.HTTP,
            url="http://mock-mcp-upstream.internal/rpc",
            timeout=10.0,
        )
        client = AsyncMCPClient(config=config)
        client._is_connected = True

        call_attempts = 0
        attempt_timestamps: list[float] = []

        async def mock_flapping_post(url: str, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
            nonlocal call_attempts
            attempt_timestamps.append(time.monotonic())
            call_attempts += 1
            request = httpx.Request("POST", url)

            if call_attempts == 1:
                # 1st attempt: 502 Bad Gateway
                resp = httpx.Response(502, request=request, text="Bad Gateway")
                resp.raise_for_status()
                raise RuntimeError("unreachable")
            elif call_attempts == 2:
                # 2nd attempt: 503 Service Unavailable
                resp = httpx.Response(503, request=request, text="Service Unavailable")
                resp.raise_for_status()
                raise RuntimeError("unreachable")
            else:
                # 3rd attempt: 200 OK
                return httpx.Response(
                    200,
                    request=request,
                    json={
                        "jsonrpc": "2.0",
                        "id": json.get("id"),
                        "result": {
                            "content": [{"type": "text", "text": "Successfully recovered from flapping network"}],
                            "isError": False,
                        },
                    },
                )

        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=mock_flapping_post)
        client._http_client = mock_http

        # Use realistic sleep tracking with accelerated backoff
        real_sleep = asyncio.sleep
        sleep_intervals: list[float] = []

        async def tracked_sleep(delay: float) -> None:
            sleep_intervals.append(delay)
            # Sleep small fraction to keep test fast while yielding to event loop
            await real_sleep(0.01)

        with patch("asyncio.sleep", side_effect=tracked_sleep):
            result = await client.call_tool("flapping_tool", {"param": "value"})

        assert call_attempts == 3, f"Expected 3 attempts, got {call_attempts}"
        assert not result.isError, f"Call should succeed, but got error: {result.content}"
        assert len(result.content) > 0
        assert "Successfully recovered" in result.content[0]["text"]

        # Verify exponential backoff intervals were computed: 0.5s for attempt 0, 1.0s for attempt 1
        assert len(sleep_intervals) == 2
        assert sleep_intervals[0] == pytest.approx(0.5, abs=0.05)
        assert sleep_intervals[1] == pytest.approx(1.0, abs=0.05)

    @pytest.mark.asyncio
    async def test_mcp_flapping_permanent_exhaustion_504(self) -> None:
        """Verify that permanent 504 Gateway Timeout exhausts 2 retries (3 attempts) and fails."""
        config = MCPServerConfig(
            name="failing_service",
            transport=MCPTransportType.HTTP,
            url="http://mock-mcp-upstream.internal/rpc",
            timeout=10.0,
        )
        client = AsyncMCPClient(config=config)
        client._is_connected = True

        call_attempts = 0

        async def mock_504_post(url: str, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
            nonlocal call_attempts
            call_attempts += 1
            request = httpx.Request("POST", url)
            resp = httpx.Response(504, request=request, text="Gateway Timeout")
            resp.raise_for_status()
            raise RuntimeError("unreachable")

        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=mock_504_post)
        client._http_client = mock_http

        with patch("asyncio.sleep", return_value=None):
            result = await client.call_tool("timeout_tool", {})

        assert call_attempts == 3, f"Expected 3 attempts before exhaustion, got {call_attempts}"
        assert result.isError is True
        assert "MCP tool network failure" in result.content[0]["text"]
        assert "504" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_mcp_non_retryable_http_error_fails_immediately(self) -> None:
        """Verify that non-retryable 500 Internal Server Error fails fast on attempt 1."""
        config = MCPServerConfig(
            name="fatal_service",
            transport=MCPTransportType.HTTP,
            url="http://mock-mcp-upstream.internal/rpc",
            timeout=10.0,
        )
        client = AsyncMCPClient(config=config)
        client._is_connected = True

        call_attempts = 0

        async def mock_500_post(url: str, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
            nonlocal call_attempts
            call_attempts += 1
            request = httpx.Request("POST", url)
            resp = httpx.Response(500, request=request, text="Fatal Internal Server Error")
            resp.raise_for_status()
            raise RuntimeError("unreachable")

        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=mock_500_post)
        client._http_client = mock_http

        result = await client.call_tool("fatal_tool", {})

        # Should fail fast without retry
        assert call_attempts == 1, f"Non-retryable 500 should only attempt once, got {call_attempts}"
        assert result.isError is True
        assert "MCP tool network failure" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_mcp_hard_timeout_simulated_hang(self) -> None:
        """Verify hard timeout aborts hanging MCP call and returns structured error result."""
        config = MCPServerConfig(
            name="hanging_service",
            transport=MCPTransportType.HTTP,
            url="http://mock-mcp-upstream.internal/rpc",
            timeout=10.0,
        )
        client = AsyncMCPClient(config=config)
        client._is_connected = True

        async def hanging_post(url: str, json: dict[str, Any], **kwargs: Any) -> httpx.Response:
            # Simulate upstream server hanging for 5.0 seconds
            await asyncio.sleep(5.0)
            return httpx.Response(200, request=httpx.Request("POST", url), json={})

        mock_http = MagicMock()
        mock_http.post = AsyncMock(side_effect=hanging_post)
        client._http_client = mock_http

        t0 = time.monotonic()
        result = await client.call_tool("slow_tool", timeout=0.2)
        elapsed = time.monotonic() - t0

        assert elapsed < 0.5, f"Timeout should fire quickly (~0.2s), took {elapsed:.3f}s"
        assert result.isError is True
        assert "Execution timed out after 0.2s" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_mcp_mock_transport_timeout(self) -> None:
        """Verify mock transport tool handler timeout guard functions identically."""
        config = MCPServerConfig(
            name="mock_hanging",
            transport=MCPTransportType.MOCK,
            timeout=10.0,
        )
        client = AsyncMCPClient(config=config)
        await client.connect()

        async def slow_mock_handler(**kwargs: Any) -> str:
            await asyncio.sleep(2.0)
            return "Too late"

        client.register_mock_tool(
            MCPToolMeta(
                name="slow_mock_action",
                description="Simulated slow mock tool",
            ),
            handler=slow_mock_handler,
        )

        t0 = time.monotonic()
        result = await client.call_tool("slow_mock_action", timeout=0.15)
        elapsed = time.monotonic() - t0

        assert elapsed < 0.4, f"Mock tool timeout should fire around 0.15s, took {elapsed:.3f}s"
        assert result.isError is True
        assert "Execution timed out after 0.15s" in result.content[0]["text"]


# ============================================================================
# Part 2: REL-04 Greeting Service Timeout & Sub-Millisecond Fallback Benchmark
# ============================================================================


class TestGreetingTimeoutAndFallbackStress:
    """Empirical tests for Proactive Greeting Service 3.0s SLA and microsecond fallback."""

    @pytest.mark.asyncio
    async def test_greeting_slow_llm_enforces_3s_timeout(
        self,
        async_db_session: Any,
        storage_manager: FileStorageManager,
        seed_test_user: User,
    ) -> None:
        """Verify greeting service bounds slow LLM to 3.0s and returns deterministic greeting."""
        async def slow_agenerate(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(6.0)
            return "Should never be reached due to 3.0s timeout."

        mock_llm = MagicMock(spec=BaseLLMAdapter)
        mock_llm.agenerate = AsyncMock(side_effect=slow_agenerate)

        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage_manager,
            llm_adapter=mock_llm,
        )

        t0 = time.monotonic()
        response: GreetingResponse = await service.generate_greeting(user_id=seed_test_user.id)
        elapsed = time.monotonic() - t0

        assert 2.8 <= elapsed <= 3.8, f"Expected timeout near 3.0s, actual elapsed: {elapsed:.2f}s"
        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0
        assert "Should never be reached" not in response.greeting
        # Must return valid Korean persona greeting
        assert any(k in response.greeting for k in ["TARS", "시스템", "명령", "대기", "파트너"])

    def test_greeting_fallback_sub_millisecond_benchmark(
        self,
        async_db_session: Any,
        storage_manager: FileStorageManager,
    ) -> None:
        """Benchmark 1,000 iterations of _generate_fallback_greeting to prove p99 latency < 1.0ms."""
        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage_manager,
            llm_adapter=None,
        )

        scenarios = [
            ("work", "오전", 9, 300, 0.90),
            ("companion", "오후", 15, 7200, 0.85),
            ("companion", "심야/새벽", 23, 100000, 0.95),
            ("companion", "심야/새벽", 3, 200000, 0.70),
            ("companion", "아침", 8, 86400 * 3, 0.90),
        ]

        durations: list[float] = []
        for i in range(1000):
            mode, period, hour, idle, humor = scenarios[i % len(scenarios)]
            t_start = time.perf_counter()
            result = service._generate_fallback_greeting(
                mode=mode,
                time_period=period,
                hour=hour,
                idle_seconds=idle,
                humor_level=humor,
            )
            t_end = time.perf_counter()
            durations.append(t_end - t_start)
            assert len(result) > 0

        durations.sort()
        p50 = durations[int(len(durations) * 0.50)]
        p95 = durations[int(len(durations) * 0.95)]
        p99 = durations[int(len(durations) * 0.99)]
        max_t = durations[-1]

        # Empirical proof: p99 latency must be strictly under 1.0 millisecond (0.001s)
        assert p99 < 0.001, f"p99 latency ({p99*1000:.3f}ms) exceeded 1.0ms threshold!"
        assert p95 < 0.0005, f"p95 latency ({p95*1000:.3f}ms) should be under 0.5ms"
        assert p50 < 0.0001, f"p50 latency ({p50*1000:.3f}ms) should be under 0.1ms"
        assert max_t < 0.01, f"Max latency ({max_t*1000:.3f}ms) should be under 10ms"

    @pytest.mark.asyncio
    async def test_greeting_llm_immediate_failure_fast_fallback(
        self,
        async_db_session: Any,
        storage_manager: FileStorageManager,
        seed_test_user: User,
    ) -> None:
        """Verify that when LLM throws an immediate error, fallback returns in < 50ms."""
        mock_llm = MagicMock(spec=BaseLLMAdapter)
        mock_llm.agenerate = AsyncMock(side_effect=RuntimeError("Cloud Quota Exceeded 429"))

        service = ProactiveGreetingService(
            db_session=async_db_session,
            storage_manager=storage_manager,
            llm_adapter=mock_llm,
        )

        t0 = time.monotonic()
        response = await service.generate_greeting(user_id=seed_test_user.id)
        elapsed = time.monotonic() - t0

        assert elapsed < 0.1, f"Immediate failure fallback took too long: {elapsed:.3f}s"
        assert isinstance(response, GreetingResponse)
        assert len(response.greeting) > 0


# ============================================================================
# Part 3: REL-05 Topic Shift 2.0s Latency Budget
# ============================================================================


class TestTopicShiftLatencyBudgetStress:
    """Empirical tests for Topic Shift Detector 2.0s cloud budget."""

    @pytest.mark.asyncio
    async def test_topic_shift_realistic_cloud_latency_1_2s_success(self) -> None:
        """Verify topic shift succeeds with realistic 1.2s cloud latency (would fail on legacy 0.5s)."""
        async def realistic_cloud_agenerate(*args: Any, **kwargs: Any) -> str:
            # 1.2s cloud generation latency
            await asyncio.sleep(1.2)
            return json.dumps({
                "is_topic_shift": True,
                "confidence": 0.92,
                "new_topic": "Interstellar Gargantua Physics",
                "reasoning": "User switched from daily greeting to astrophysics.",
            })

        mock_llm = MagicMock()
        mock_llm.agenerate = AsyncMock(side_effect=realistic_cloud_agenerate)

        detector = TopicShiftDetector(llm_adapter=mock_llm)
        turns = [
            HumanMessage(content="좋은 아침이야 TARS."),
            AIMessage(content="좋은 아침입니다, 파트너."),
        ]

        t0 = time.monotonic()
        result = await detector.detect_topic_shift(
            recent_turns=turns,
            new_query="가르강튀아의 중력 렌즈 효과와 조석력에 대해 설명해줘.",
        )
        elapsed = time.monotonic() - t0

        assert 1.15 <= elapsed <= 1.5, f"Expected ~1.2s elapsed time, got {elapsed:.2f}s"
        assert result.is_topic_shift is True
        assert result.new_topic == "Interstellar Gargantua Physics"

    @pytest.mark.asyncio
    async def test_topic_shift_cloud_timeout_exceeded(self) -> None:
        """Verify topic shift times out gracefully when LLM exceeds 2.0s and defaults to False."""
        async def hanging_cloud_agenerate(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(3.5)
            return json.dumps({"is_topic_shift": True, "new_topic": "Late Topic"})

        mock_llm = MagicMock()
        mock_llm.agenerate = AsyncMock(side_effect=hanging_cloud_agenerate)

        detector = TopicShiftDetector(llm_adapter=mock_llm)
        turns = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
        ]

        t0 = time.monotonic()
        result = await detector.detect_topic_shift(
            recent_turns=turns,
            new_query="Tell me about Mars",
        )
        elapsed = time.monotonic() - t0

        assert 1.9 <= elapsed <= 2.5, f"Expected timeout near 2.0s, got {elapsed:.2f}s"
        assert result.is_topic_shift is False
        assert result.new_topic is None

    @pytest.mark.asyncio
    async def test_topic_shift_caller_timeout_override(self) -> None:
        """Verify caller can pass custom timeout override (e.g. 0.1s fast check)."""
        async def slow_agenerate(*args: Any, **kwargs: Any) -> str:
            await asyncio.sleep(0.5)
            return json.dumps({"is_topic_shift": True, "new_topic": "Override"})

        mock_llm = MagicMock()
        mock_llm.agenerate = AsyncMock(side_effect=slow_agenerate)

        detector = TopicShiftDetector(llm_adapter=mock_llm)
        turns = [HumanMessage(content="Hi"), AIMessage(content="Hello")]

        t0 = time.monotonic()
        result = await detector.detect_topic_shift(
            recent_turns=turns,
            new_query="Custom query",
            timeout_seconds=0.1,
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 0.25
        assert result.is_topic_shift is False

    @pytest.mark.asyncio
    async def test_topic_shift_adversarial_malformed_json(self) -> None:
        """Verify detector handles hallucinated non-JSON output without raising unhandled exceptions."""
        mock_llm = MagicMock()
        mock_llm.agenerate = AsyncMock(
            return_value="Sure! As an AI, I believe ```json {is_topic_shift: YES NOT VALID JSON}```"
        )

        detector = TopicShiftDetector(llm_adapter=mock_llm)
        turns = [HumanMessage(content="Hi"), AIMessage(content="Hello")]

        result = await detector.detect_topic_shift(
            recent_turns=turns,
            new_query="Arbitrary question",
        )

        assert result.is_topic_shift is False
        assert result.new_topic is None


# ============================================================================
# Part 4: SEC-01 CORS Adversarial Attacks & Credentialed Preflights
# ============================================================================


class TestCORSAdversarialAttacks:
    """Empirical security tests challenging CORS origin whitelist against attack vectors."""

    @pytest.mark.asyncio
    async def test_cors_illegal_origins_and_subdomain_spoofing(self) -> None:
        """Verify that evil domains, subdomain spoofs, null origins, and port shifts are rejected."""
        app = create_app()
        transport = ASGITransport(app=app)

        adversarial_origins = [
            "http://evil-attacker.com",
            "https://evil-attacker.com",
            "http://localhost:3000.attacker.com",
            "http://attacker-localhost:3000",
            "http://localhost:3000@evil.com",
            "http://localhost:3001",
            "http://localhost:8080",
            "http://127.0.0.1:9999",
            "https://localhost:3000",
            "null",
        ]

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            for origin in adversarial_origins:
                res = await client.get("/health", headers={"Origin": origin})
                assert res.status_code == 200
                allow_origin = res.headers.get("access-control-allow-origin")
                assert allow_origin != origin, f"Vulnerability! Adversarial origin {origin} was reflected!"
                assert allow_origin is None, f"Untrusted origin {origin} should receive no CORS header"

    @pytest.mark.asyncio
    async def test_cors_credentialed_preflight_attacks(self) -> None:
        """Verify preflight OPTIONS requests strictly validate origin before admitting credentials."""
        app = create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Attacker preflight
            evil_res = await client.options(
                "/api/v1/chat/greeting",
                headers={
                    "Origin": "http://malicious-site.org",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization, Content-Type, X-Correlation-ID",
                },
            )
            assert evil_res.status_code == 400
            assert evil_res.headers.get("access-control-allow-origin") is None

            # 2. Legitimate preflight
            valid_res = await client.options(
                "/api/v1/chat/greeting",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization, Content-Type, X-Correlation-ID",
                },
            )
            assert valid_res.status_code == 200
            assert valid_res.headers.get("access-control-allow-origin") == "http://localhost:3000"
            assert valid_res.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_cors_wildcard_credential_invariant(self) -> None:
        """Enforce strict invariant: Access-Control-Allow-Origin MUST NEVER be '*' with credentials."""
        app = create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/health", headers={"Origin": "http://localhost:3000"})
            if res.headers.get("access-control-allow-credentials") == "true":
                assert res.headers.get("access-control-allow-origin") != "*"


# ============================================================================
# Part 5: ASY-06 Burst Extractions & Semaphore(10) Throttling Stress
# ============================================================================


class TestBackgroundExtractionSemaphoreThrottlingStress:
    """Empirical concurrency stress tests for ASY-06 bounded semaphore."""

    @pytest.fixture(autouse=True)
    def reset_semaphore_fixture(self) -> Any:
        """Ensure each async test function receives a clean, current-loop bound semaphore."""
        import tars.services.agent_chat as ac
        ac._EXTRACTION_SEMAPHORE = asyncio.Semaphore(10)
        yield
        ac._EXTRACTION_SEMAPHORE = asyncio.Semaphore(10)

    @pytest.mark.asyncio
    async def test_burst_30_extractions_peak_concurrency_bounded(self) -> None:
        """Verify 30 concurrent extractions never exceed 10 peak concurrent tasks (ASY-06)."""
        current_concurrency = 0
        peak_concurrency = 0
        completed_count = 0
        lock = asyncio.Lock()

        async def monitored_extract_and_sync(*args: Any, **kwargs: Any) -> list[Any]:
            nonlocal current_concurrency, peak_concurrency, completed_count
            async with lock:
                current_concurrency += 1
                if current_concurrency > peak_concurrency:
                    peak_concurrency = current_concurrency

            # Hold permit to create concurrent contention across all 30 tasks
            await asyncio.sleep(0.03)

            async with lock:
                current_concurrency -= 1
                completed_count += 1

            return [MagicMock()]

        mock_db = AsyncMock()
        mock_factory = MagicMock(return_value=mock_db)
        mock_storage = MagicMock()
        mock_turns = [HumanMessage(content="Data point"), AIMessage(content="Acknowledged")]

        with (
            patch("tars.services.agent_chat.get_session_factory", return_value=mock_factory),
            patch("tars.services.agent_chat.SelfEvolvingKnowledgeWorker.extract_and_sync", side_effect=monitored_extract_and_sync),
        ):
            tasks = [
                asyncio.create_task(
                    execute_background_knowledge_extraction(
                        user_id=f"burst_user_{i}",
                        conversation_turns=mock_turns,
                        storage=mock_storage,
                    )
                )
                for i in range(30)
            ]
            await asyncio.gather(*tasks)

        # Empirical Assertions:
        assert peak_concurrency <= 10, f"Violation of ASY-06! Peak concurrency reached {peak_concurrency} > 10"
        assert peak_concurrency == 10, f"Expected semaphore saturation (peak == 10), got {peak_concurrency}"
        assert completed_count == 30, f"Expected 30 completed tasks, got {completed_count}"
        assert get_extraction_semaphore()._value == 10, "Semaphore permits were not fully restored"

    @pytest.mark.asyncio
    async def test_burst_extractions_chaos_resilience(self) -> None:
        """Verify semaphore permits return to 10 under chaos: 10 success, 10 errors, 10 cancellations."""
        lock = asyncio.Lock()
        active_workers = 0
        peak_workers = 0

        worker_gate = asyncio.Event()

        async def chaos_worker(user_id: str, *args: Any, **kwargs: Any) -> list[Any]:
            nonlocal active_workers, peak_workers
            async with lock:
                active_workers += 1
                if active_workers > peak_workers:
                    peak_workers = active_workers

            task_idx = int(user_id.split("_")[-1])
            if 10 <= task_idx < 20:
                async with lock:
                    active_workers -= 1
                raise RuntimeError(f"Simulated unhandled DB/Worker exception for {user_id}")

            try:
                await worker_gate.wait()
            finally:
                async with lock:
                    active_workers -= 1

            return [MagicMock()]

        mock_db = AsyncMock()
        mock_factory = MagicMock(return_value=mock_db)
        mock_storage = MagicMock()
        mock_turns = [HumanMessage(content="Query"), AIMessage(content="Answer")]

        with (
            patch("tars.services.agent_chat.get_session_factory", return_value=mock_factory),
            patch("tars.services.agent_chat.SelfEvolvingKnowledgeWorker.extract_and_sync", side_effect=chaos_worker),
        ):
            tasks = [
                asyncio.create_task(
                    execute_background_knowledge_extraction(
                        user_id=f"chaos_user_{i}",
                        conversation_turns=mock_turns,
                        storage=mock_storage,
                    )
                )
                for i in range(30)
            ]

            # Yield so tasks 0..9 acquire semaphore permits and block on worker_gate
            await asyncio.sleep(0.01)

            # Cancel tasks 20..29 while queued on semaphore
            for i in range(20, 30):
                tasks[i].cancel()

            # Release gate to allow running tasks to complete
            worker_gate.set()

            results = await asyncio.gather(*tasks, return_exceptions=True)

        assert peak_workers <= 10, f"Peak concurrency during chaos exceeded 10: {peak_workers}"
        # Verify 10 cancelled
        cancelled_count = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        assert cancelled_count == 10, f"Expected 10 cancelled tasks, got {cancelled_count}"

        # Crucial invariant: semaphore must recover all 10 permits with zero leak
        assert get_extraction_semaphore()._value == 10, "Semaphore permit leaked during chaos!"


# ============================================================================
# Part 6: OBS-03 & OBS-04 Readiness Probes & Prometheus Metrics Telemetry
# ============================================================================


class TestObservabilityReadinessAndPrometheusMetricsStress:
    """Empirical tests for OBS-03 readiness deep probe and OBS-04 Prometheus metrics."""

    @pytest.mark.asyncio
    async def test_readiness_probe_healthy_200(self) -> None:
        """Verify readiness probe returns 200 OK when DB and storage filesystem are healthy."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/health/readiness")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "ready"
            assert data["overall"] == "ok"
            assert data["database"] == "connected"
            assert data["storage"] == "accessible"

    @pytest.mark.asyncio
    async def test_readiness_probe_severed_db_503(self) -> None:
        """Verify readiness probe returns 503 Service Unavailable when DB connection is severed."""
        app = create_app()
        transport = ASGITransport(app=app)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = ConnectionResetError("Severed DB connection pool")
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__.return_value = mock_session
        mock_factory.return_value.__aexit__.return_value = None

        with patch("tars.api.routers.health.get_session_factory", return_value=mock_factory):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.get("/health/readiness")
                assert res.status_code == 503
                data = res.json()
                assert data["status"] == "degraded"
                assert "Severed DB connection pool" in data["error"]
                assert "unhealthy" in data["database"]
                assert data["storage"] == "accessible"

    @pytest.mark.asyncio
    async def test_readiness_probe_readonly_disk_503(self) -> None:
        """Verify readiness probe returns 503 Service Unavailable when storage disk is read-only."""
        app = create_app()
        transport = ASGITransport(app=app)

        mock_storage = MagicMock()
        mock_base = MagicMock()
        mock_base.mkdir.side_effect = PermissionError("Read-only file system: /data/storage")
        mock_storage.base_dir = mock_base

        with patch("tars.api.routers.health.get_storage_manager", return_value=mock_storage):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.get("/health/readiness")
                assert res.status_code == 503
                data = res.json()
                assert data["status"] == "degraded"
                assert "Read-only file system" in data["error"]
                assert "unhealthy" in data["storage"]
                assert data["database"] == "connected"

    @pytest.mark.asyncio
    async def test_readiness_probe_dual_subsystem_failure_503(self) -> None:
        """Verify readiness probe returns 503 and reports both failures when DB and disk fail."""
        app = create_app()
        transport = ASGITransport(app=app)

        mock_session = AsyncMock()
        mock_session.execute.side_effect = TimeoutError("DB query timeout")
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__.return_value = mock_session
        mock_factory.return_value.__aexit__.return_value = None

        mock_storage = MagicMock()
        mock_base = MagicMock()
        mock_base.mkdir.side_effect = OSError("Disk I/O error")
        mock_storage.base_dir = mock_base

        with (
            patch("tars.api.routers.health.get_session_factory", return_value=mock_factory),
            patch("tars.api.routers.health.get_storage_manager", return_value=mock_storage),
        ):
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.get("/health/readiness")
                assert res.status_code == 503
                data = res.json()
                assert data["status"] == "degraded"
                assert "database" in data["error"]
                assert "storage" in data["error"]

    @pytest.mark.asyncio
    async def test_prometheus_metrics_request_counting_and_self_exclusion(self) -> None:
        """Verify HTTP requests increment tars_http_requests_total, and /metrics excludes itself."""
        app = create_app()
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Send initial baseline request
            await client.get("/health")

            # Read initial metrics
            res1 = await client.get("/metrics")
            assert res1.status_code == 200

            def parse_request_count(metrics_text: str, endpoint: str) -> float:
                pattern = rf'tars_http_requests_total\{{[^}}]*endpoint="{re.escape(endpoint)}"[^}}]*\}}\s+([0-9.]+)'
                matches = re.findall(pattern, metrics_text)
                return sum(float(m) for m in matches)

            initial_count = parse_request_count(res1.text, "/health")

            # Fire 10 sequential requests to /health
            for _ in range(10):
                resp = await client.get("/health")
                assert resp.status_code == 200

            # Read updated metrics
            res2 = await client.get("/metrics")
            updated_count = parse_request_count(res2.text, "/health")

            assert updated_count == initial_count + 10, f"Expected {initial_count + 10}, got {updated_count}"

            # Verify /metrics itself is never tracked in tars_http_requests_total
            metrics_endpoint_count = parse_request_count(res2.text, "/metrics")
            assert metrics_endpoint_count == 0.0, "/metrics route was erroneously recorded in metrics!"

    @pytest.mark.asyncio
    async def test_prometheus_circuit_breaker_gauge_transitions(self) -> None:
        """Verify circuit breaker transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED) update Prometheus."""
        app = create_app()
        transport = ASGITransport(app=app)

        cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

        def read_gauge(metrics_text: str) -> float:
            match = re.search(r"tars_circuit_breaker_state\s+([0-9.]+)", metrics_text)
            assert match is not None, "tars_circuit_breaker_state gauge missing from /metrics output"
            return float(match.group(1))

        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Initially CLOSED (0.0)
            cb.reset()
            res = await client.get("/metrics")
            assert read_gauge(res.text) == 0.0

            # 2. Trigger failures to trip OPEN (2.0)
            cb.record_failure()
            cb.record_failure()
            assert cb.state == CircuitState.OPEN
            res = await client.get("/metrics")
            assert read_gauge(res.text) == 2.0

            # 3. Elapse recovery timeout -> transitions to HALF_OPEN (1.0)
            await asyncio.sleep(0.12)
            assert cb.allow_request() is True
            assert str(cb.state.value) == "half_open"
            res = await client.get("/metrics")
            assert read_gauge(res.text) == 1.0

            # 4. Success probe -> transitions to CLOSED (0.0)
            cb.record_success()
            assert str(cb.state.value) == "closed"
            res = await client.get("/metrics")
            assert read_gauge(res.text) == 0.0
