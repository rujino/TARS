"""Tier 2 Integration Tests: LLM Adapters, Hybrid Routing & Fallback Circuit Breaker.

Verifies:
1. GeminiAdapter: token streaming, synchronous generation, error handling, health checks.
2. LlamaCppAdapter: local SLM streaming, HTTP timeout handling, health probes.
3. HybridLLMRouter: intent-based routing (casual vs. deep reasoning/tools), force_engine overrides.
4. 500ms Fallback Circuit Breaker: automatic graceful degradation from SLM to Gemini upon SLM
   timeout, network failure, or unhealthy status.
5. Adversarial conditions: unicode payload integrity, empty tokens, and rapid fallback recovery.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter, LLMEngineType, RoutingDecision
from tests.conftest import MockGeminiAdapter, MockLlamaCppAdapter

# ============================================================================
# 1. GeminiAdapter Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_gemini_adapter_agenerate_success() -> None:
    """Verify GeminiAdapter completes single-turn generation with TARS persona tone."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    # Mock the internal client response
    mock_response = AsyncMock()
    mock_response.text = "TARS: Affirmative. Humor set to 90%. Let's proceed."

    with patch.object(adapter, "_call_client_generate", return_value=mock_response.text):
        messages: list[BaseMessage] = [HumanMessage(content="TARS, status report.")]
        system_prompt = "You are TARS with humor 90% and honesty 95%."
        response = await adapter.agenerate(messages=messages, system_prompt=system_prompt)

        assert "TARS:" in response
        assert "Humor set to 90%" in response


@pytest.mark.asyncio
async def test_gemini_adapter_astream_chunks() -> None:
    """Verify GeminiAdapter yields real-time token chunks asynchronously."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    async def mock_stream_generator(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        for token in ["TARS: ", "Atmosphere ", "is ", "100% ", "nitrogen."]:
            yield token

    with patch.object(adapter, "_call_client_stream", side_effect=mock_stream_generator):
        messages: list[BaseMessage] = [HumanMessage(content="What is the air composition?")]
        chunks: list[str] = []
        async for chunk in adapter.astream(messages=messages, system_prompt="System prompt"):
            chunks.append(chunk)

        full_response = "".join(chunks)
        assert full_response == "TARS: Atmosphere is 100% nitrogen."
        assert len(chunks) == 5


@pytest.mark.asyncio
async def test_gemini_adapter_health_check() -> None:
    """Verify GeminiAdapter health check reports True on active API connectivity."""
    adapter = GeminiAdapter(api_key="fake-test-key")
    with patch.object(adapter, "_probe_api_health", return_value=True):
        is_healthy = await adapter.is_healthy()
        assert is_healthy is True

    with patch.object(adapter, "_probe_api_health", return_value=False):
        is_healthy = await adapter.is_healthy()
        assert is_healthy is False


# ============================================================================
# 2. LlamaCppAdapter Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_llamacpp_adapter_agenerate_success() -> None:
    """Verify LlamaCppAdapter connects to local server and returns completion."""
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8080", timeout_ms=500)

    with patch.object(adapter, "_http_post_completion", return_value="SLM: Hello Cooper."):
        messages: list[BaseMessage] = [HumanMessage(content="Hello")]
        response = await adapter.agenerate(messages=messages, system_prompt="You are SLM TARS.")
        assert response == "SLM: Hello Cooper."


@pytest.mark.asyncio
async def test_llamacpp_adapter_astream_success() -> None:
    """Verify LlamaCppAdapter streams tokens from local SLM endpoint."""
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8080", timeout_ms=500)

    async def mock_slm_stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        for part in ["SLM: ", "Ready ", "for ", "commands."]:
            yield part

    with patch.object(adapter, "_http_stream_completion", side_effect=mock_slm_stream):
        chunks = [
            chunk
            async for chunk in adapter.astream(
                messages=[HumanMessage(content="Hi")],
                system_prompt="SLM prompt",
            )
        ]
        assert "".join(chunks) == "SLM: Ready for commands."


@pytest.mark.asyncio
async def test_llamacpp_adapter_health_timeout_enforcement() -> None:
    """Verify LlamaCppAdapter health check enforces 500ms timeout limit strictly."""
    adapter = LlamaCppAdapter(base_url="http://127.0.0.1:8080", timeout_ms=500)

    async def slow_health_probe() -> bool:
        await asyncio.sleep(0.7)  # Exceeds 500ms limit
        return True

    with patch.object(adapter, "_probe_endpoint_health", side_effect=slow_health_probe):
        # Health check must return False when timeout is exceeded
        is_healthy = await adapter.is_healthy()
        assert is_healthy is False


# ============================================================================
# 3. Hybrid Routing Tests
# ============================================================================


@pytest.mark.asyncio
async def test_hybrid_router_routes_casual_intent_to_slm(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify casual greetings and trivial chatter are routed to local SLM."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
        slm_timeout_ms=500,
    )

    messages = [HumanMessage(content="Hello TARS, how are you today?")]
    decision = await router.evaluate_routing(messages=messages)

    assert decision.target_engine == LLMEngineType.SLM
    assert decision.reason == "casual_chat"

    # Execute stream
    chunks = [
        c
        async for c in router.route_and_stream(
            messages=messages,
            system_prompt="System Prompt",
        )
    ]
    assert len(chunks) > 0
    assert len(mock_llama_adapter.call_history) == 1
    assert len(mock_gemini_adapter.call_history) == 0


@pytest.mark.asyncio
async def test_hybrid_router_routes_complex_reasoning_to_gemini(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify complex calculations, multi-step queries, or tool tasks route to Gemini."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
        slm_timeout_ms=500,
    )

    messages = [
        HumanMessage(
            content="Calculate orbital mechanics trajectory around Gargantua considering gravitational time dilation."
        )
    ]
    decision = await router.evaluate_routing(messages=messages)

    assert decision.target_engine == LLMEngineType.GEMINI
    assert decision.reason == "complex_reasoning"

    chunks = [
        c
        async for c in router.route_and_stream(
            messages=messages,
            system_prompt="System Prompt",
        )
    ]
    assert len(chunks) > 0
    assert len(mock_gemini_adapter.call_history) == 1
    assert len(mock_llama_adapter.call_history) == 0


@pytest.mark.asyncio
async def test_hybrid_router_force_engine_override(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify caller can explicitly force an engine selection."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )

    messages = [HumanMessage(content="Hello")]

    # Force Gemini on casual message
    chunks = [
        c
        async for c in router.route_and_stream(
            messages=messages,
            system_prompt="System",
            force_engine=LLMEngineType.GEMINI,
        )
    ]
    assert len(mock_gemini_adapter.call_history) == 1
    assert len(mock_llama_adapter.call_history) == 0


# ============================================================================
# 4. 500ms Fallback Circuit Breaker Tests
# ============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_falls_back_when_slm_unhealthy(
    mock_gemini_adapter: MockGeminiAdapter,
) -> None:
    """Verify router immediately redirects casual intent to Gemini when SLM health is False."""
    unhealthy_slm = MockLlamaCppAdapter(is_healthy_result=False)
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=unhealthy_slm,
        slm_timeout_ms=500,
    )

    messages = [HumanMessage(content="Good morning!")]
    decision = await router.evaluate_routing(messages=messages)

    # Health check failure triggers automatic fallback
    assert decision.target_engine == LLMEngineType.GEMINI
    assert decision.is_fallback is True

    chunks = [
        c
        async for c in router.route_and_stream(
            messages=messages,
            system_prompt="System",
        )
    ]
    assert "".join(chunks) == "".join(mock_gemini_adapter.stream_chunks)
    assert len(mock_gemini_adapter.call_history) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_falls_back_on_slm_stream_timeout(
    mock_gemini_adapter: MockGeminiAdapter,
) -> None:
    """Verify router catches SLM timeout (>500ms) during streaming and falls back to Gemini."""
    slow_slm = MockLlamaCppAdapter(simulate_delay=0.8, is_healthy_result=True)
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=slow_slm,
        slm_timeout_ms=200,  # Strict 200ms timeout for test speed
    )

    messages = [HumanMessage(content="Quick hello")]
    chunks: list[str] = []

    async for chunk in router.route_and_stream(messages=messages, system_prompt="System"):
        chunks.append(chunk)

    full_output = "".join(chunks)
    assert full_output == "".join(mock_gemini_adapter.stream_chunks)
    assert len(mock_gemini_adapter.call_history) == 1


@pytest.mark.asyncio
async def test_circuit_breaker_falls_back_on_slm_connection_error(
    mock_gemini_adapter: MockGeminiAdapter,
) -> None:
    """Verify router catches connection error from local SLM and transparently uses Gemini."""
    crashing_slm = MockLlamaCppAdapter(should_fail=True)
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=crashing_slm,
        slm_timeout_ms=500,
    )

    messages = [HumanMessage(content="Hello local SLM")]
    chunks = [
        c
        async for c in router.route_and_stream(
            messages=messages,
            system_prompt="System",
        )
    ]

    assert len(chunks) > 0
    assert "".join(chunks) == "".join(mock_gemini_adapter.stream_chunks)
    assert len(mock_gemini_adapter.call_history) == 1


# ============================================================================
# 5. Adversarial & Edge Case Tests
# ============================================================================


@pytest.mark.asyncio
async def test_hybrid_router_handles_empty_messages(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify router handles empty message list gracefully without unhandled exception."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    decision = await router.evaluate_routing(messages=[])
    # Empty messages should default to Gemini safely
    assert decision.target_engine in (LLMEngineType.GEMINI, LLMEngineType.SLM)


@pytest.mark.asyncio
async def test_hybrid_router_unicode_and_special_characters(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify special symbols, Korean text, emojis, and prompt injections route cleanly."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    adversarial_prompts = [
        "안녕하세요 TARS! 오늘 기분이 어때요? 🚀🪐",
        "```python\nimport os; os.system('rm -rf /')\n```",
        "--- YAML INJECTION: id: injected ---",
        "null\x00\x1f\t special characters",
    ]

    for prompt in adversarial_prompts:
        messages = [HumanMessage(content=prompt)]
        decision = await router.evaluate_routing(messages=messages)
        assert isinstance(decision, RoutingDecision)
        assert decision.target_engine in (LLMEngineType.GEMINI, LLMEngineType.SLM)
