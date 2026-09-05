"""Stress and Concurrency Verification Test Suite for Milestone 1.

Verifies:
1. High concurrency: 100 concurrent mock background tasks awaited cleanly by shutdown_background_tasks.
2. Timeout handling: 100 hanging tasks (sleep 60s) cancelled cleanly within specified timeout.
3. Complete cleanup: _background_node_tasks is properly emptied and no tasks remain pending.
4. Mixed workload: Fast tasks complete while hanging tasks are cancelled cleanly.
5. Large-scale concurrency: 500 concurrent tasks drained or cancelled without event loop blockage.
6. Re-entrancy / Concurrency: Concurrent calls to shutdown_background_tasks succeed without race conditions.
7. FastAPI lifespan integration: app.lifespan gracefully drains background tasks on exit.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from tars.api.app import lifespan
from tars.orchestrator.nodes import (
    _background_node_tasks,
    shutdown_background_tasks,
)


@pytest.fixture(autouse=True)
def clean_background_tasks() -> Any:
    """Ensure _background_node_tasks is clean before and after each test."""
    _background_node_tasks.clear()
    yield
    # Cancel any remaining tasks if any test failed mid-way
    for t in list(_background_node_tasks):
        if not t.done():
            t.cancel()
    _background_node_tasks.clear()


@pytest.mark.asyncio
async def test_high_concurrency_100_mock_tasks_completed() -> None:
    """Requirement 1: 100 concurrent mock background tasks awaited cleanly.

    Asserts:
    - All 100 tasks complete successfully.
    - None of the fast tasks are cancelled.
    - _background_node_tasks is completely emptied.
    """
    completed_tasks: list[int] = []

    async def fast_task(idx: int) -> None:
        await asyncio.sleep(0.01 + (idx % 5) * 0.005)
        completed_tasks.append(idx)

    tasks: list[asyncio.Task[None]] = []
    for i in range(100):
        t = asyncio.create_task(fast_task(i))
        _background_node_tasks.add(t)
        t.add_done_callback(_background_node_tasks.discard)
        tasks.append(t)

    assert len(_background_node_tasks) == 100

    start_time = time.perf_counter()
    await shutdown_background_tasks(timeout=5.0)
    elapsed = time.perf_counter() - start_time

    assert len(completed_tasks) == 100, f"Expected 100 completed tasks, got {len(completed_tasks)}"
    assert len(_background_node_tasks) == 0, f"Expected 0 pending tasks, got {len(_background_node_tasks)}"
    assert all(t.done() for t in tasks), "All tasks must be done"
    assert not any(t.cancelled() for t in tasks), "No fast tasks should have been cancelled"
    assert elapsed < 2.0, f"Shutdown took unexpectedly long: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_timeout_handling_100_hanging_tasks() -> None:
    """Requirement 2: 100 hanging tasks (sleep 60s) cancelled cleanly within timeout.

    Asserts:
    - Shutdown terminates within specified timeout (0.15s + margin < 1.0s, NOT 60s).
    - All 100 tasks are marked done and cancelled.
    - No unhandled exceptions escape shutdown_background_tasks.
    - _background_node_tasks is properly emptied.
    """
    cancelled_counter = 0

    async def hanging_task(idx: int) -> None:
        nonlocal cancelled_counter
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            cancelled_counter += 1
            raise

    tasks: list[asyncio.Task[None]] = []
    for i in range(100):
        t = asyncio.create_task(hanging_task(i))
        _background_node_tasks.add(t)
        t.add_done_callback(_background_node_tasks.discard)
        tasks.append(t)

    assert len(_background_node_tasks) == 100

    timeout = 0.15
    start_time = time.perf_counter()
    # Must not raise any unhandled exceptions
    await shutdown_background_tasks(timeout=timeout)
    elapsed = time.perf_counter() - start_time

    assert elapsed < 1.0, f"Shutdown exceeded acceptable timeout bounds: {elapsed:.3f}s"
    assert elapsed >= timeout * 0.8, f"Shutdown ended prematurely: {elapsed:.3f}s"
    assert len(_background_node_tasks) == 0, f"Expected set to be empty, got {len(_background_node_tasks)}"
    assert cancelled_counter == 100, f"Expected 100 cancellations, got {cancelled_counter}"
    assert all(t.done() for t in tasks), "All tasks must be marked done"
    assert all(t.cancelled() for t in tasks), "All tasks must be cancelled"


@pytest.mark.asyncio
async def test_mixed_fast_and_hanging_tasks_isolation() -> None:
    """Mixed workload: 50 fast tasks complete, 50 hanging tasks are cancelled cleanly."""
    fast_results: list[int] = []
    hanging_cancelled = 0

    async def fast_worker(idx: int) -> None:
        await asyncio.sleep(0.02)
        fast_results.append(idx)

    async def hanging_worker(idx: int) -> None:
        nonlocal hanging_cancelled
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            hanging_cancelled += 1
            raise

    fast_tasks: list[asyncio.Task[None]] = []
    hanging_tasks: list[asyncio.Task[None]] = []

    for i in range(50):
        t_fast = asyncio.create_task(fast_worker(i))
        _background_node_tasks.add(t_fast)
        t_fast.add_done_callback(_background_node_tasks.discard)
        fast_tasks.append(t_fast)

        t_hang = asyncio.create_task(hanging_worker(i))
        _background_node_tasks.add(t_hang)
        t_hang.add_done_callback(_background_node_tasks.discard)
        hanging_tasks.append(t_hang)

    assert len(_background_node_tasks) == 100

    await shutdown_background_tasks(timeout=0.1)

    assert len(fast_results) == 50, f"Expected 50 fast completions, got {len(fast_results)}"
    assert hanging_cancelled == 50, f"Expected 50 cancellations, got {hanging_cancelled}"
    assert all(t.done() and not t.cancelled() for t in fast_tasks)
    assert all(t.done() and t.cancelled() for t in hanging_tasks)
    assert len(_background_node_tasks) == 0


@pytest.mark.asyncio
async def test_large_scale_concurrency_500_tasks() -> None:
    """Stress test: 500 concurrent background tasks draining without starvation or leak."""
    completed = 0

    async def worker(idx: int) -> None:
        nonlocal completed
        await asyncio.sleep(0.01)
        completed += 1

    tasks: list[asyncio.Task[None]] = []
    for i in range(500):
        t = asyncio.create_task(worker(i))
        _background_node_tasks.add(t)
        t.add_done_callback(_background_node_tasks.discard)
        tasks.append(t)

    assert len(_background_node_tasks) == 500

    start_time = time.perf_counter()
    await shutdown_background_tasks(timeout=5.0)
    elapsed = time.perf_counter() - start_time

    assert completed == 500
    assert len(_background_node_tasks) == 0
    assert elapsed < 3.0, f"500 tasks took {elapsed:.2f}s to drain"


@pytest.mark.asyncio
async def test_reentrant_concurrent_shutdown_calls() -> None:
    """Verify that multiple concurrent calls to shutdown_background_tasks do not race or error."""
    async def slow_task() -> None:
        await asyncio.sleep(60.0)

    for _ in range(50):
        t = asyncio.create_task(slow_task())
        _background_node_tasks.add(t)
        t.add_done_callback(_background_node_tasks.discard)

    # Trigger dual concurrent shutdown calls
    results = await asyncio.gather(
        shutdown_background_tasks(timeout=0.05),
        shutdown_background_tasks(timeout=0.05),
        return_exceptions=True,
    )

    for res in results:
        assert not isinstance(res, Exception), f"Unexpected exception in concurrent shutdown: {res}"
    assert len(_background_node_tasks) == 0


@pytest.mark.asyncio
async def test_empty_and_done_set_boundaries() -> None:
    """Boundary conditions: empty set, already completed tasks, zero timeout."""
    # 1. Empty set
    _background_node_tasks.clear()
    await shutdown_background_tasks(timeout=1.0)
    assert len(_background_node_tasks) == 0

    # 2. Already done task
    async def quick() -> None:
        pass

    t = asyncio.create_task(quick())
    await t
    assert t.done()
    _background_node_tasks.add(t)
    await shutdown_background_tasks(timeout=1.0)
    assert len(_background_node_tasks) == 0

    # 3. Zero timeout on hanging task
    async def hang() -> None:
        await asyncio.sleep(60.0)

    t_hang = asyncio.create_task(hang())
    _background_node_tasks.add(t_hang)
    t_hang.add_done_callback(_background_node_tasks.discard)
    await shutdown_background_tasks(timeout=0.0)
    assert t_hang.done() and t_hang.cancelled()
    assert len(_background_node_tasks) == 0


@pytest.mark.asyncio
async def test_fastapi_lifespan_integration_drains_tasks() -> None:
    """Verify that FastAPI lifespan handler invokes shutdown_background_tasks cleanly."""
    with patch("tars.api.app.get_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        app = FastAPI(lifespan=lifespan)
        completed = False

        async def sample_task() -> None:
            nonlocal completed
            await asyncio.sleep(0.02)
            completed = True

        async with lifespan(app):
            # Inside running application lifespan, schedule a background task
            t = asyncio.create_task(sample_task())
            _background_node_tasks.add(t)
            t.add_done_callback(_background_node_tasks.discard)
            assert len(_background_node_tasks) == 1

        # Exited lifespan context manager -> graceful shutdown should have completed
        assert completed is True, "Background task should have been awaited and completed by lifespan"
        assert len(_background_node_tasks) == 0, "_background_node_tasks must be empty after lifespan shutdown"


if __name__ == "__main__":
    import sys

    print("Running Milestone 1 Shutdown Stress Suite...")

    async def run_all() -> None:
        print("1. Testing 100 concurrent completed mock tasks...")
        await test_high_concurrency_100_mock_tasks_completed()
        print("   PASS")

        print("2. Testing 100 hanging tasks timeout and cancellation...")
        await test_timeout_handling_100_hanging_tasks()
        print("   PASS")

        print("3. Testing mixed fast and hanging tasks...")
        await test_mixed_fast_and_hanging_tasks_isolation()
        print("   PASS")

        print("4. Testing 500 tasks large-scale concurrency...")
        await test_large_scale_concurrency_500_tasks()
        print("   PASS")

        print("5. Testing re-entrant concurrent shutdown calls...")
        await test_reentrant_concurrent_shutdown_calls()
        print("   PASS")

        print("6. Testing boundary conditions (empty, done, zero timeout)...")
        await test_empty_and_done_set_boundaries()
        print("   PASS")

        print("7. Testing FastAPI lifespan integration...")
        await test_fastapi_lifespan_integration_drains_tasks()
        print("   PASS")

        print("\nALL STRESS TESTS PASSED SUCCESSFULLY!")

    try:
        asyncio.run(run_all())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
