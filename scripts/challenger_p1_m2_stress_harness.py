#!/usr/bin/env python3
"""Empirical Stress Harness: ASY-03 & REL-02 (Phase 1 Milestone 2).

Challenger: challenger_p1_m2_1
Adversarial Stress Target:
1. ASY-03: Event loop non-blocking behavior under synchronous stream consumption,
   strict chunk ordering, stop_event propagation, and producer thread cleanup within 100ms.
2. REL-02: Rapid client disconnect propagation during SSE and WebSocket generation,
   immediate server halt of token generation, and zero orphan LLM tasks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure in-memory SQLite is used before database modules load
os.environ.setdefault("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Pre-import google.genai types so initial Python import is not counted as event loop jitter
try:
    from google.genai import types  # noqa: F401
except Exception:
    pass

from httpx import ASGITransport, AsyncClient
from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.testclient import TestClient

from tars.adapters.gemini import (
    GeminiAdapter,
    _consume_sync_stream_safely,
)
from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_current_user, get_db_session
from tars.core.security import create_access_token
from tars.db.base import Base
from tars.db.models import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("challenger_p1_m2")


class MockSyncChunk:
    """Mock Gemini chunk for synchronous stream simulation."""

    def __init__(self, text: str) -> None:
        self.text = text


# ============================================================================
# Database Infrastructure Setup
# ============================================================================


async def setup_test_db() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Initialize pristine SQLite in-memory database with required tables and seed user."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        user = User(
            id="user_stress_harness",
            username="challenger_user",
            email="challenger@test.space",
            is_active=True,
            hashed_password="hashed_pw_test",
        )
        session.add(user)
        await session.commit()

    return engine, session_factory


# ============================================================================
# Experiment 1: ASY-03 Event Loop Non-blocking & Strict Chunk Ordering
# ============================================================================


async def run_asy03_event_loop_latency_test() -> bool:
    """Empirically measure event loop jitter while concurrently consuming synchronous streams."""
    logger.info("=== [EXP 1] ASY-03: Concurrent Sync Stream Event Loop Non-blocking Test ===")

    concurrency = 10
    chunks_per_stream = 20
    chunk_sleep_sec = 0.01  # 10ms blocking sleep per chunk = 2.0s cumulative blocking sleep

    # Heartbeat ticker configuration: target interval = 5ms (0.005s)
    heartbeat_interval = 0.005
    heartbeat_latencies: list[float] = []
    heartbeat_running = True

    async def heartbeat_worker() -> None:
        nonlocal heartbeat_running
        last_time = time.perf_counter()
        while heartbeat_running:
            await asyncio.sleep(heartbeat_interval)
            now = time.perf_counter()
            delta = now - last_time
            heartbeat_latencies.append(delta * 1000.0)
            last_time = now

    heartbeat_task = asyncio.create_task(heartbeat_worker())
    await asyncio.sleep(0.01)  # Warm up ticker
    heartbeat_latencies.clear()

    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    def sync_generator_factory(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            for i in range(chunks_per_stream):
                time.sleep(chunk_sleep_sec)  # Blocking synchronous sleep in worker thread
                yield MockSyncChunk(f"chunk_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = sync_generator_factory

    stream_results: dict[int, list[str]] = {}

    async def consume_one_stream(stream_id: int) -> None:
        received: list[str] = []
        async for token in adapter.astream([HumanMessage(content=f"Stream {stream_id}")]):
            received.append(token)
        stream_results[stream_id] = received

    # Execute concurrent streams
    start_time = time.perf_counter()
    with patch.object(adapter, "_get_client", return_value=mock_client):
        tasks = [asyncio.create_task(consume_one_stream(i)) for i in range(concurrency)]
        await asyncio.gather(*tasks)
    total_duration = time.perf_counter() - start_time

    heartbeat_running = False
    await heartbeat_task

    # Verification:
    # 1. Chunk count and ordering
    all_chunks_correct = True
    for s_id in range(concurrency):
        tokens = stream_results.get(s_id, [])
        expected = [f"chunk_{i} " for i in range(chunks_per_stream)]
        if tokens != expected:
            logger.error("Stream %d chunk mismatch! Got %d tokens, expected %d", s_id, len(tokens), len(expected))
            all_chunks_correct = False

    # 2. Heartbeat metrics
    total_ticks = len(heartbeat_latencies)
    avg_latency_ms = (sum(heartbeat_latencies) / total_ticks) if total_ticks else 0.0
    max_latency_ms = max(heartbeat_latencies) if total_ticks else 0.0

    logger.info(
        "ASY-03 Concurrency Results: Streams=%d, Total Chunks=%d in %.3fs. Heartbeat Ticks=%d, Avg Latency=%.2fms, Max Latency=%.2fms",
        concurrency,
        concurrency * chunks_per_stream,
        total_duration,
        total_ticks,
        avg_latency_ms,
        max_latency_ms,
    )

    assert all_chunks_correct, "Stream chunks were dropped or received out-of-order"
    assert total_ticks >= 20, f"Heartbeat was starved! Total ticks: {total_ticks}"
    assert max_latency_ms < 50.0, f"Max event loop latency spiked to {max_latency_ms:.2f}ms (threshold: 50ms)"

    logger.info("PASS: ASY-03 Event loop remained non-blocking and all chunks arrived strictly ordered.")
    return True


# ============================================================================
# Experiment 2: ASY-03 Abrupt Cancellation & Thread Cleanup <= 100ms
# ============================================================================


async def run_asy03_thread_cleanup_test() -> bool:
    """Verify abrupt consumer cancellation signals stop_event and terminates producer thread <= 100ms."""
    logger.info("=== [EXP 2] ASY-03: Abrupt Cancellation & Thread Cleanup <= 100ms ===")

    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    def infinite_sync_generator(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            for i in range(1000):
                time.sleep(0.01)
                yield MockSyncChunk(f"token_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = infinite_sync_generator

    captured_threads: list[threading.Thread] = []
    original_thread_init = threading.Thread.__init__

    def intercept_thread_init(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        original_thread_init(self, *args, **kwargs)
        if kwargs.get("target") == _consume_sync_stream_safely:
            captured_threads.append(self)

    # Test 2.1: Early break termination
    with patch.object(threading.Thread, "__init__", side_effect=intercept_thread_init, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            received = []
            async for chunk in adapter.astream([HumanMessage(content="Test cancel")]):
                received.append(chunk)
                if len(received) >= 3:
                    break

    assert len(captured_threads) == 1, "Failed to capture producer thread"
    producer_thread = captured_threads[0]

    # Non-blocking poll on event loop for thread termination
    t0 = time.perf_counter()
    for _ in range(20):
        await asyncio.sleep(0.005)
        if not producer_thread.is_alive():
            break
    cleanup_duration_ms = (time.perf_counter() - t0) * 1000.0

    is_alive = producer_thread.is_alive()
    logger.info(
        "Early break thread cleanup: is_alive=%s, cleanup_duration=%.2fms",
        is_alive,
        cleanup_duration_ms,
    )
    assert not is_alive, f"Producer thread did not terminate within 100ms! Alive={is_alive}"
    assert cleanup_duration_ms < 100.0

    # Test 2.2: Cancellation via task.cancel()
    captured_threads.clear()
    with patch.object(threading.Thread, "__init__", side_effect=intercept_thread_init, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            async def run_and_wait() -> None:
                async for _ in adapter.astream([HumanMessage(content="Cancel via task")]):
                    await asyncio.sleep(0.001)

            task = asyncio.create_task(run_and_wait())
            await asyncio.sleep(0.03)  # Let it start
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert len(captured_threads) == 1
    producer_thread = captured_threads[0]

    t0 = time.perf_counter()
    for _ in range(20):
        await asyncio.sleep(0.005)
        if not producer_thread.is_alive():
            break
    cleanup_duration_ms = (time.perf_counter() - t0) * 1000.0

    is_alive = producer_thread.is_alive()
    logger.info(
        "Task cancel thread cleanup: is_alive=%s, cleanup_duration=%.2fms",
        is_alive,
        cleanup_duration_ms,
    )
    assert not is_alive, "Producer thread remained alive after asyncio.CancelledError"
    assert cleanup_duration_ms < 100.0

    # Test 2.3: Rapid cancellation storm (30 rapid cycles)
    logger.info("Running rapid cancellation storm (30 iterations)...")
    storm_threads: list[threading.Thread] = []

    def storm_thread_intercept(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        original_thread_init(self, *args, **kwargs)
        if kwargs.get("target") == _consume_sync_stream_safely:
            storm_threads.append(self)

    with patch.object(threading.Thread, "__init__", side_effect=storm_thread_intercept, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            for _ in range(30):
                async for _ in adapter.astream([HumanMessage(content="Storm item")]):
                    break

    await asyncio.sleep(0.1)
    alive_threads = [t for t in storm_threads if t.is_alive()]
    logger.info("Storm complete: 30 threads launched, alive count=%d", len(alive_threads))
    assert len(alive_threads) == 0, f"Thread leak detected! {len(alive_threads)} threads still alive."

    logger.info("PASS: ASY-03 Producer threads terminate cleanly within 100ms with zero leaks.")
    return True


# ============================================================================
# Experiment 3: REL-02 SSE Rapid Client Disconnect Propagation
# ============================================================================


async def run_rel02_sse_disconnect_test(
    session_factory: async_sessionmaker[AsyncSession],
    user: User,
) -> bool:
    """Verify rapid client disconnect during SSE stream halts server generation immediately."""
    logger.info("=== [EXP 3] REL-02: SSE Rapid Client Disconnect Propagation ===")

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user

    async def override_get_db() -> Any:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    tokens_produced = 0
    generator_finally_called = False

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        nonlocal tokens_produced, generator_finally_called
        try:
            for i in range(100):
                tokens_produced += 1
                await asyncio.sleep(0.005)
                yield f"tok_{i} "
        finally:
            generator_finally_called = True

    call_count = 0

    async def mock_is_disconnected(self: Any) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3  # Disconnect after stream_start + 1 token

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream), \
         patch("starlette.requests.Request.is_disconnected", new=mock_is_disconnected), \
         patch("tars.api.routers.chat.logger.info") as mock_log:

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/chat/stream",
                json={"session_id": "sess_sse_harness_1", "message": "Trigger SSE"},
            )

        assert resp.status_code == 200

        # Wait 100ms to allow background processing
        await asyncio.sleep(0.1)

        logger.info(
            "SSE Stream terminated: tokens_produced=%d, generator_finally_called=%s",
            tokens_produced,
            generator_finally_called,
        )

        assert tokens_produced <= 5, f"Downstream generation continued after disconnect! Produced: {tokens_produced}"
        assert generator_finally_called is True, "Stream generator finally block was not executed"

        disconnect_logged = any(
            "Client disconnected from SSE stream" in str(arg)
            for call in mock_log.call_args_list
            for arg in call.args
        )
        assert disconnect_logged, "Disconnect log message was not emitted"

    logger.info("PASS: REL-02 SSE stream generation halted immediately on client disconnect.")
    return True


# ============================================================================
# Experiment 4: REL-02 WebSocket Rapid Client Disconnect Propagation
# ============================================================================


def run_rel02_websocket_disconnect_test(
    session_factory: async_sessionmaker[AsyncSession],
    user: User,
) -> bool:
    """Verify rapid client disconnect during WebSocket streaming halts generation immediately."""
    logger.info("=== [EXP 4] REL-02: WebSocket Rapid Client Disconnect Propagation ===")

    app = create_app()
    test_user_token = create_access_token({"sub": user.id, "username": user.username})

    tokens_produced = 0
    generator_closed = False

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        nonlocal tokens_produced, generator_closed
        try:
            for i in range(100):
                tokens_produced += 1
                await asyncio.sleep(0.01)
                yield f"ws_tok_{i} "
        finally:
            generator_closed = True

    with patch("tars.api.routers.chat.get_session_factory", return_value=session_factory), \
         patch("tars.services.agent_chat.get_session_factory", return_value=session_factory), \
         patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream):

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
            ws.send_json({"type": "chat_message", "session_id": "ws_harness_1", "content": "Hello TARS"})

            # Read stream_start
            f1 = ws.receive_json()
            assert f1.get("type") == "stream_start"

            # Read first token
            f2 = ws.receive_json()
            assert f2.get("type") == "token"

            # Abrupt client disconnect mid-turn
            ws.close()

        time.sleep(0.05)

        logger.info(
            "WebSocket turn terminated: tokens_produced=%d, generator_closed=%s",
            tokens_produced,
            generator_closed,
        )

        assert tokens_produced < 10, f"WebSocket generation continued after client disconnect: {tokens_produced}"
        assert generator_closed is True, "WebSocket underlying generator was not closed on disconnect"

    logger.info("PASS: REL-02 WebSocket stream generation halted immediately on client disconnect.")
    return True


# ============================================================================
# Main Runner & Empirical Verdict
# ============================================================================


async def main_async() -> int:
    logger.info("Starting Empirical Stress Harness for Milestone 2 (ASY-03, REL-02)...")

    engine, session_factory = await setup_test_db()
    async with session_factory() as session:
        user = await session.get(User, "user_stress_harness")
        assert user is not None

    results = []

    # 1. ASY-03
    try:
        r1 = await run_asy03_event_loop_latency_test()
        results.append(("ASY-03 Event Loop Non-blocking & Order", r1))
    except Exception as e:
        logger.error("EXP 1 FAILED: %s", e, exc_info=True)
        results.append(("ASY-03 Event Loop Non-blocking & Order", False))

    try:
        r2 = await run_asy03_thread_cleanup_test()
        results.append(("ASY-03 Thread Cleanup <= 100ms", r2))
    except Exception as e:
        logger.error("EXP 2 FAILED: %s", e, exc_info=True)
        results.append(("ASY-03 Thread Cleanup <= 100ms", False))

    # 2. REL-02
    try:
        r3 = await run_rel02_sse_disconnect_test(session_factory, user)
        results.append(("REL-02 SSE Disconnect Propagation", r3))
    except Exception as e:
        logger.error("EXP 3 FAILED: %s", e, exc_info=True)
        results.append(("REL-02 SSE Disconnect Propagation", False))

    try:
        r4 = run_rel02_websocket_disconnect_test(session_factory, user)
        results.append(("REL-02 WebSocket Disconnect Propagation", r4))
    except Exception as e:
        logger.error("EXP 4 FAILED: %s", e, exc_info=True)
        results.append(("REL-02 WebSocket Disconnect Propagation", False))

    logger.info("================ EMPIRICAL TEST SUMMARY ================")
    all_passed = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        logger.info("  [%s] %s", status, name)
        if not passed:
            all_passed = False

    await engine.dispose()

    if all_passed:
        logger.info("VERDICT: APPROVE (All empirical stress tests satisfied)")
        return 0
    else:
        logger.error("VERDICT: REJECT (One or more empirical stress tests failed)")
        return 1


def main() -> None:
    code = asyncio.run(main_async())
    sys.exit(code)


if __name__ == "__main__":
    main()
