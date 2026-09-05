"""Tier 2 Integration Tests: GeminiAdapter Synchronous Stream Concurrency & Loop Unblocking (ASY-03).

Verifies:
1. Event Loop Non-Blocking:
   - When Gemini client falls back to the synchronous SDK stream (`response_stream`),
     the main asyncio event loop is NOT blocked while chunks are iterated.
   - Concurrently scheduled async tasks (e.g. event loop tick counter) continue
     to execute freely during token delivery.
2. Cooperative Early Cancellation:
   - Breaking early from the async generator sets `stop_event` and cooperatively
     halts the producer thread.
3. Exception Propagation:
   - Network errors or iterator failures in the background producer thread
     are cleanly dispatched and re-raised in the consuming coroutine.
4. Thread Producer Sentinel Protocol:
   - `_consume_sync_stream_safely` delivers all chunks and final sentinel to queue.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_gemini_sync_stream_event_loop_unblocked() -> None:
    """Verify that synchronous stream iteration does not starve the asyncio event loop."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    # A synchronous generator that simulates blocking network socket reads (40ms per chunk)
    def sync_blocking_stream() -> Any:
        tokens = ["TARS: ", "Synchronous ", "stream ", "producer ", "active."]
        for t in tokens:
            time.sleep(0.04)  # Blocking sleep simulating socket read
            yield MockSyncChunk(t)

    # Configure client without native aio/astream to force the sync fallback path
    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.return_value = sync_blocking_stream()

    # Background async ticker to verify event loop liveness
    ticks = 0
    ticker_running = True

    async def event_loop_ticker() -> None:
        nonlocal ticks
        while ticker_running:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker_task = asyncio.create_task(event_loop_ticker())

    chunks: list[str] = []
    with patch.object(adapter, "_get_client", return_value=mock_client):
        async for chunk in adapter.astream([HumanMessage(content="Status report")]):
            chunks.append(chunk)

    ticker_running = False
    await ticker_task

    # 1. Verify all chunks were properly received
    assert "".join(chunks) == "TARS: Synchronous stream producer active."
    assert len(chunks) == 5

    # 2. Verify event loop executed concurrent tasks while sync stream was blocking
    # 5 chunks * 40ms = 200ms total blocking time; ticker runs every 10ms -> expected >= 8 ticks
    assert ticks >= 5, f"Event loop was starved! Expected >= 5 ticks, but got {ticks}"


@pytest.mark.asyncio
async def test_gemini_sync_stream_early_break_stops_thread() -> None:
    """Verify breaking early from astream halts the background producer thread."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    produced_count = 0
    stopped = threading.Event()

    def infinite_sync_stream() -> Any:
        nonlocal produced_count
        for i in range(100):
            if stopped.is_set():
                break
            produced_count += 1
            time.sleep(0.02)
            yield MockSyncChunk(f"token_{i} ")

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.return_value = infinite_sync_stream()

    received: list[str] = []
    with patch.object(adapter, "_get_client", return_value=mock_client):
        async for chunk in adapter.astream([HumanMessage(content="Stream 100")]):
            received.append(chunk)
            if len(received) >= 2:
                break  # Consumer exits early

    # Allow background thread a moment to observe stop_event and terminate
    await asyncio.sleep(0.08)

    assert len(received) == 2
    # Background thread should have broken early, well before producing 100 items
    assert produced_count < 20, f"Thread produced too many chunks: {produced_count}"


@pytest.mark.asyncio
async def test_gemini_sync_stream_exception_propagation() -> None:
    """Verify that exceptions raised during sync stream iteration are propagated to the caller."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    def failing_sync_stream() -> Any:
        yield MockSyncChunk("First chunk.")
        raise ConnectionResetError("Gemini sync stream socket closed abruptly")

    mock_client = MagicMock()
    del mock_client.aio
    del mock_client.astream
    mock_client.models.generate_content_stream.return_value = failing_sync_stream()

    with patch.object(adapter, "_get_client", return_value=mock_client):
        with pytest.raises(ConnectionResetError, match="Gemini sync stream socket closed abruptly"):
            async for _ in adapter.astream([HumanMessage(content="Trigger error")]):
                pass


@pytest.mark.asyncio
async def test_consume_sync_stream_safely_unit() -> None:
    """Direct unit test of _consume_sync_stream_safely helper function."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    stop_event = threading.Event()

    raw_chunks = [MockSyncChunk("A"), MockSyncChunk("B"), MockSyncChunk("C")]

    # Run helper in a daemon thread
    thread = threading.Thread(
        target=_consume_sync_stream_safely,
        args=(raw_chunks, loop, queue, stop_event),
        daemon=True,
    )
    thread.start()

    # Asynchronously await items from the queue
    items: list[Any] = []
    while True:
        item = await queue.get()
        items.append(item)
        if item is _STREAM_SENTINEL:
            break

    thread.join(timeout=1.0)

    assert len(items) == 4
    assert [c.text for c in items[:3]] == ["A", "B", "C"]
    assert items[3] is _STREAM_SENTINEL


@pytest.mark.asyncio
async def test_gemini_native_async_stream_takes_priority() -> None:
    """Verify that if native client.aio is available, it is prioritized over sync fallback."""
    adapter = GeminiAdapter(api_key="fake-test-key", model_name="gemini-2.0-flash")

    mock_client = MagicMock()
    del mock_client.astream  # Prevent fallback to LangChain astream

    async def mock_async_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in [MockSyncChunk("Native "), MockSyncChunk("async.")]:
            yield chunk

    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=mock_async_stream())

    with patch.object(adapter, "_get_client", return_value=mock_client):
        chunks: list[str] = []
        async for chunk in adapter.astream([HumanMessage(content="Test async priority")]):
            chunks.append(chunk)

        assert "".join(chunks) == "Native async."
        mock_client.aio.models.generate_content_stream.assert_called_once()
