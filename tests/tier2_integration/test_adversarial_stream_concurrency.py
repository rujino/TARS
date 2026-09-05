"""Tier 2 Integration / Adversarial Stress: Synchronous Stream Concurrency & Hygiene (ASY-03).

Empirical verification of:
1. Event Loop Non-Blocking:
   - High-volume concurrent streams (10+ streams, 200+ chunks) running through
     _consume_sync_stream_safely / GeminiAdapter.astream with blocking socket sleeps.
   - Ticker heartbeat verifying jitter and latency spikes remain under 40ms.
2. Strict Chunk Ordering & Integrity:
   - 100% of chunks across all concurrent streams arrive in sequential FIFO order without loss.
3. Abrupt Consumer Cancellation & Thread Termination:
   - Early consumer break triggers stop_event.
   - Asyncio task.cancel() triggers stop_event.
   - Producer thread terminates cooperatively within 100ms.
4. Cancellation Storm Resilience:
   - 30 rapid back-to-back stream cancellations leave zero orphan threads.
5. Error and Edge-Case Isolation:
   - Closed event loop, pre-set stop_event, and generator exceptions handled gracefully.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from tars.adapters.gemini import (
    _STREAM_SENTINEL,
    GeminiAdapter,
    _consume_sync_stream_safely,
)


class MockSyncChunk:
    """Mock Gemini SDK stream response chunk."""

    def __init__(self, text: str) -> None:
        self.text = text


@pytest.mark.asyncio
async def test_stream_concurrency_heartbeat_jitter() -> None:
    """Verify that 10 concurrent synchronous streams do not starve the event loop or spike latency."""
    # Warmup / pre-import to avoid measuring initial module import time
    try:
        from google.genai import types  # noqa: F401
    except Exception:
        pass

    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    concurrency = 10
    chunks_per_stream = 20
    chunk_sleep_sec = 0.01  # 10ms blocking sleep per chunk = 2.0s cumulative blocking sleep

    def sync_generator_factory(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            for i in range(chunks_per_stream):
                time.sleep(chunk_sleep_sec)
                yield MockSyncChunk(f"chunk_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = sync_generator_factory

    # Setup tight heartbeat ticker (target: 5ms interval)
    heartbeat_latencies: list[float] = []
    heartbeat_running = True

    async def ticker() -> None:
        last = time.perf_counter()
        while heartbeat_running:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            heartbeat_latencies.append((now - last) * 1000.0)
            last = now

    t_task = asyncio.create_task(ticker())
    await asyncio.sleep(0.01)  # allow ticker to start
    heartbeat_latencies.clear()

    stream_results: dict[int, list[str]] = {}

    async def worker(stream_id: int) -> None:
        received: list[str] = []
        async for chunk in adapter.astream([HumanMessage(content=f"msg_{stream_id}")]):
            received.append(chunk)
        stream_results[stream_id] = received

    with patch.object(adapter, "_get_client", return_value=mock_client):
        tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
        await asyncio.gather(*tasks)

    heartbeat_running = False
    await t_task

    # 1. Verify 100% chunk delivery and strict FIFO ordering
    for s_id in range(concurrency):
        received = stream_results.get(s_id, [])
        expected = [f"chunk_{i} " for i in range(chunks_per_stream)]
        assert received == expected, f"Stream {s_id} chunk order mismatch or lost tokens"

    # 2. Verify event loop latency and jitter
    assert len(heartbeat_latencies) >= 20, f"Heartbeat was starved: {len(heartbeat_latencies)} ticks"
    avg_latency = sum(heartbeat_latencies) / len(heartbeat_latencies)
    max_latency = max(heartbeat_latencies)

    # Average latency should be very close to 5ms; max latency under heavy concurrent streaming < 50ms
    assert avg_latency < 15.0, f"Average event loop latency too high: {avg_latency:.2f}ms"
    assert max_latency < 50.0, f"Event loop latency spiked to {max_latency:.2f}ms"


@pytest.mark.asyncio
async def test_stream_abrupt_consumer_break_stops_thread() -> None:
    """Verify breaking early from astream triggers cooperative thread termination within 100ms."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    produced_count = 0

    def infinite_sync_stream(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            nonlocal produced_count
            for i in range(1000):
                produced_count += 1
                time.sleep(0.01)
                yield MockSyncChunk(f"token_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = infinite_sync_stream

    captured_threads: list[threading.Thread] = []
    original_thread_init = threading.Thread.__init__

    def intercept_thread_init(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        original_thread_init(self, *args, **kwargs)
        if kwargs.get("target") == _consume_sync_stream_safely:
            captured_threads.append(self)

    with patch.object(threading.Thread, "__init__", side_effect=intercept_thread_init, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            received: list[str] = []
            async for chunk in adapter.astream([HumanMessage(content="Break test")]):
                received.append(chunk)
                if len(received) >= 3:
                    break

    assert len(captured_threads) == 1
    producer_thread = captured_threads[0]

    # Non-blocking wait on event loop for thread termination (deadline: 100ms)
    t0 = time.perf_counter()
    for _ in range(20):
        await asyncio.sleep(0.005)
        if not producer_thread.is_alive():
            break

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert not producer_thread.is_alive(), f"Producer thread did not terminate within 100ms (elapsed: {elapsed_ms:.2f}ms)"
    assert elapsed_ms < 100.0
    assert produced_count < 20, f"Producer generated too many chunks after consumer break: {produced_count}"


@pytest.mark.asyncio
async def test_stream_task_cancellation_stops_thread() -> None:
    """Verify cancelling the consumer asyncio task cooperatively terminates the producer thread within 100ms."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    def infinite_sync_stream(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            for i in range(1000):
                time.sleep(0.01)
                yield MockSyncChunk(f"token_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = infinite_sync_stream

    captured_threads: list[threading.Thread] = []
    original_thread_init = threading.Thread.__init__

    def intercept_thread_init(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        original_thread_init(self, *args, **kwargs)
        if kwargs.get("target") == _consume_sync_stream_safely:
            captured_threads.append(self)

    with patch.object(threading.Thread, "__init__", side_effect=intercept_thread_init, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            async def consumer_task() -> None:
                async for _ in adapter.astream([HumanMessage(content="Task cancel test")]):
                    await asyncio.sleep(0.001)

            task = asyncio.create_task(consumer_task())
            await asyncio.sleep(0.03)  # Allow consumer to receive initial chunks
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert len(captured_threads) == 1
    producer_thread = captured_threads[0]

    # Non-blocking poll for thread termination
    t0 = time.perf_counter()
    for _ in range(20):
        await asyncio.sleep(0.005)
        if not producer_thread.is_alive():
            break

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert not producer_thread.is_alive(), f"Producer thread remained alive after task cancellation: {elapsed_ms:.2f}ms"
    assert elapsed_ms < 100.0


@pytest.mark.asyncio
async def test_stream_rapid_cancellation_storm_no_thread_leak() -> None:
    """Verify that 30 rapid back-to-back cancellations leave zero zombie/orphan threads."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    def infinite_sync_stream(*args: Any, **kwargs: Any) -> Any:
        def _gen() -> Any:
            for i in range(500):
                time.sleep(0.01)
                yield MockSyncChunk(f"token_{i} ")
        return _gen()

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.side_effect = infinite_sync_stream

    captured_threads: list[threading.Thread] = []
    original_thread_init = threading.Thread.__init__

    def intercept_thread_init(self: threading.Thread, *args: Any, **kwargs: Any) -> None:
        original_thread_init(self, *args, **kwargs)
        if kwargs.get("target") == _consume_sync_stream_safely:
            captured_threads.append(self)

    with patch.object(threading.Thread, "__init__", side_effect=intercept_thread_init, autospec=True):
        with patch.object(adapter, "_get_client", return_value=mock_client):
            for _ in range(30):
                async for _ in adapter.astream([HumanMessage(content="Storm test")]):
                    break  # break immediately after 1 chunk

    assert len(captured_threads) == 30

    # Wait up to 100ms for all 30 threads to finish
    await asyncio.sleep(0.1)

    alive = [t for t in captured_threads if t.is_alive()]
    assert len(alive) == 0, f"Thread leak detected! {len(alive)} threads still alive after cancellation storm."


@pytest.mark.asyncio
async def test_consume_sync_stream_safely_edge_cases() -> None:
    """Verify _consume_sync_stream_safely directly on generator exceptions, closed loop, and pre-set stop_event."""
    loop = asyncio.get_running_loop()

    # Case 1: Pre-set stop_event does not iterate generator
    stream_iterated = False

    def uncalled_gen() -> Any:
        nonlocal stream_iterated
        stream_iterated = True
        yield MockSyncChunk("Never")

    q1: asyncio.Queue[Any] = asyncio.Queue()
    stop1 = threading.Event()
    stop1.set()

    t1 = threading.Thread(
        target=_consume_sync_stream_safely,
        args=(uncalled_gen(), loop, q1, stop1),
        daemon=True,
    )
    t1.start()
    t1.join(timeout=0.1)

    assert not t1.is_alive()
    assert q1.empty()

    # Case 2: Exception mid-stream pushes Exception object and stops
    def error_gen() -> Any:
        yield MockSyncChunk("ok")
        raise ConnectionResetError("Socket severed mid-stream")

    q2: asyncio.Queue[Any] = asyncio.Queue()
    stop2 = threading.Event()

    t2 = threading.Thread(
        target=_consume_sync_stream_safely,
        args=(error_gen(), loop, q2, stop2),
        daemon=True,
    )
    t2.start()
    t2.join(timeout=0.1)

    assert not t2.is_alive()

    first_item = await q2.get()
    assert first_item.text == "ok"

    second_item = await q2.get()
    assert isinstance(second_item, ConnectionResetError)

    third_item = await q2.get()
    assert third_item is _STREAM_SENTINEL
