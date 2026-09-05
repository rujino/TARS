"""Empirical Challenger Test Suite for Milestone 1:
Background Task Concurrency Isolation & Graceful Shutdown.

Scope:
1. Client WebSocket disconnect simulation:
   Verify that when a client session terminates (raising WebSocketDisconnect
   or closing the connection), an active task in _background_node_tasks continues
   executing and is NOT cancelled.
2. Multi-user isolation simulation:
   Verify that disconnecting client A does not clear _background_node_tasks or
   cancel client B's active background task.
3. Burst concurrency and abrupt mid-stream disconnect isolation.
4. Lifespan graceful shutdown draining and timeout handling.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_storage_manager
from tars.core.security import create_access_token, get_password_hash
from tars.db.models import TARSSettings, User
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.orchestrator.nodes import _background_node_tasks, shutdown_background_tasks
from tars.storage.manager import FileStorageManager

# ==============================================================================
# Helper: Pure ASGI WebSocket Client for Async Concurrency Testing
# ==============================================================================


class AsyncASGIWebSocket:
    """Lightweight pure ASGI WebSocket client running in the same event loop."""

    def __init__(self, app: Any, path: str, query_string: str = "") -> None:
        self.app = app
        self.scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query_string.encode(),
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "subprotocols": [],
        }
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.handler_task: asyncio.Task[None] | None = None
        self.connected = False

    async def connect(self) -> None:
        self.handler_task = asyncio.create_task(
            self.app(self.scope, self.incoming.get, self.outgoing.put)
        )
        await self.incoming.put({"type": "websocket.connect"})
        msg = await self.outgoing.get()
        assert msg["type"] == "websocket.accept", f"Expected accept, got {msg}"
        self.connected = True

    async def send_json(self, data: dict[str, Any]) -> None:
        text = json.dumps(data)
        await self.incoming.put({"type": "websocket.receive", "text": text})

    async def receive_json(self) -> dict[str, Any]:
        msg = await self.outgoing.get()
        assert msg["type"] == "websocket.send", f"Expected send frame, got {msg}"
        data: dict[str, Any] = json.loads(msg["text"])
        return data

    async def disconnect(self, code: int = 1000) -> None:
        if not self.connected:
            return
        await self.incoming.put({"type": "websocket.disconnect", "code": code})
        self.connected = False
        if self.handler_task:
            try:
                await self.handler_task
            except Exception:
                pass


# ==============================================================================
# Helper for Multi-User DB Seeding
# ==============================================================================


async def _create_test_user(
    session: AsyncSession, user_id: str, username: str, email: str
) -> tuple[User, str]:
    user = User(
        id=user_id,
        username=username,
        email=email,
        hashed_password=get_password_hash("Secret123!"),
        is_active=True,
    )
    settings = TARSSettings(
        user_id=user_id,
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
    )
    session.add(user)
    session.add(settings)
    await session.commit()
    await session.refresh(user)
    token = create_access_token(data={"sub": user.id})
    return user, token


# ==============================================================================
# 1. Client WebSocket Disconnect Simulation (Single Client Resilience)
# ==============================================================================


def test_client_ws_disconnect_simulation_starlette(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    temp_storage_root: Path,
) -> None:
    """Verify that when a client session terminates (raising WebSocketDisconnect via ws.close),

    an active task in _background_node_tasks continues executing and is NOT cancelled.
    """
    _background_node_tasks.clear()
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    task_completed = False

    async def slow_extract_and_sync(*args: Any, **kwargs: Any) -> list[Any]:
        nonlocal task_completed
        await asyncio.sleep(0.3)
        task_completed = True
        return []

    mock_tokens = ["TARS: ", "Mission ", "in ", "progress."]

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker,
                "extract_and_sync",
                side_effect=slow_extract_and_sync,
            ):
                client = TestClient(app)
                with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                    ws.send_json(
                        {
                            "type": "chat_message",
                            "session_id": "session_disconnect_test",
                            "content": "Initiate background extraction.",
                        }
                    )

                    # Consume all streaming frames up to stream_end
                    while True:
                        frame = ws.receive_json()
                        if frame.get("type") == "stream_end":
                            break

                    # Background task is now dispatched in _background_node_tasks
                    assert len(_background_node_tasks) == 1, (
                        f"Expected 1 task in _background_node_tasks, got {len(_background_node_tasks)}"
                    )
                    active_task = next(iter(_background_node_tasks))
                    assert not active_task.done(), "Task should be active/pending"
                    assert not active_task.cancelled(), "Task should not be cancelled"

                    # Explicitly disconnect WebSocket from client side (raises WebSocketDisconnect on server)
                    ws.close(code=1000)

                    # Assert task remains in _background_node_tasks and is NOT cancelled
                    assert len(_background_node_tasks) == 1, (
                        "Task was prematurely cleared from _background_node_tasks!"
                    )
                    assert not active_task.cancelled(), (
                        "CRITICAL BUG: Task was cancelled upon WebSocket disconnection!"
                    )

                    # Wait for task completion
                    import time

                    t0 = time.time()
                    while not active_task.done() and time.time() - t0 < 2.0:
                        time.sleep(0.05)

                    assert active_task.done(), "Task failed to reach done state"
                    assert not active_task.cancelled(), "Task cancelled during execution"
                    assert task_completed, "Task function body did not execute to completion"

    # Verify task auto-discarded from global set upon completion
    assert len(_background_node_tasks) == 0, (
        f"Expected empty _background_node_tasks, found {len(_background_node_tasks)} lingering tasks"
    )


@pytest.mark.asyncio
async def test_client_ws_disconnect_simulation_pure_asgi(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Verify under pure ASGI async runtime that WebSocket disconnection does not cancel

    the active background task, and the task completes asynchronously.
    """
    _background_node_tasks.clear()
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        _, token = await _create_test_user(
            session, "user_pure_asgi", "pure_asgi", "pure@example.com"
        )

    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: storage

    task_completed = False

    async def slow_extract(*args: Any, **kwargs: Any) -> list[Any]:
        nonlocal task_completed
        await asyncio.sleep(0.25)
        task_completed = True
        return []

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in ["Pure ", "ASGI ", "stream."]:
            yield t

    with patch("tars.api.routers.chat.get_session_factory", return_value=session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker, "extract_and_sync", side_effect=slow_extract
            ):
                ws = AsyncASGIWebSocket(app, "/api/v1/chat/ws", f"token={token}")
                await ws.connect()
                await ws.send_json(
                    {
                        "type": "chat_message",
                        "session_id": "pure_asgi_s1",
                        "content": "Execute test",
                    }
                )

                while True:
                    frame = await ws.receive_json()
                    if frame.get("type") == "stream_end":
                        break

                assert len(_background_node_tasks) == 1
                bg_task = next(iter(_background_node_tasks))
                assert not bg_task.done()

                # Disconnect client
                await ws.disconnect(code=1000)

                # Confirm task continues running
                assert len(_background_node_tasks) == 1
                assert not bg_task.cancelled(), "Task was cancelled when client disconnected!"

                # Await task completion
                await bg_task
                assert bg_task.done()
                assert not bg_task.cancelled()
                assert task_completed

    assert len(_background_node_tasks) == 0


# ==============================================================================
# 2. Multi-User Concurrency Isolation Simulation
# ==============================================================================


@pytest.mark.asyncio
async def test_multi_user_isolation_client_a_disconnect_preserves_client_b_task(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Verify that disconnecting client A does NOT clear _background_node_tasks

    or cancel client B's active background extraction task.
    """
    _background_node_tasks.clear()
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        _, token_a = await _create_test_user(
            session, "user_alpha", "user_alpha", "alpha@example.com"
        )
        _, token_b = await _create_test_user(session, "user_beta", "user_beta", "beta@example.com")

    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: storage

    task_results: dict[str, bool] = {"user_alpha": False, "user_beta": False}

    async def extraction_worker(user_id: str, *args: Any, **kwargs: Any) -> list[Any]:
        # User A's task takes 0.3s, User B's task takes 0.5s
        sleep_duration = 0.3 if user_id == "user_alpha" else 0.5
        await asyncio.sleep(sleep_duration)
        task_results[user_id] = True
        return []

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in ["Response ", "chunk."]:
            yield chunk

    with patch("tars.api.routers.chat.get_session_factory", return_value=session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker, "extract_and_sync", side_effect=extraction_worker
            ):
                ws_a = AsyncASGIWebSocket(app, "/api/v1/chat/ws", f"token={token_a}")
                ws_b = AsyncASGIWebSocket(app, "/api/v1/chat/ws", f"token={token_b}")

                await ws_a.connect()
                await ws_b.connect()

                # User A sends message and finishes turn
                await ws_a.send_json(
                    {
                        "type": "chat_message",
                        "session_id": "session_a",
                        "content": "Message from User A",
                    }
                )
                while True:
                    f = await ws_a.receive_json()
                    if f.get("type") == "stream_end":
                        break

                # User B sends message and finishes turn
                await ws_b.send_json(
                    {
                        "type": "chat_message",
                        "session_id": "session_b",
                        "content": "Message from User B",
                    }
                )
                while True:
                    f = await ws_b.receive_json()
                    if f.get("type") == "stream_end":
                        break

                # Both tasks are now in _background_node_tasks
                assert len(_background_node_tasks) == 2, (
                    f"Expected 2 tasks in set, found {len(_background_node_tasks)}"
                )
                tasks_snapshot = list(_background_node_tasks)
                for t in tasks_snapshot:
                    assert not t.done()
                    assert not t.cancelled()

                # User A abruptly disconnects
                await ws_a.disconnect(code=1000)

                # ASSERT CRITICAL INVARIANTS:
                # 1. _background_node_tasks is NOT cleared
                assert len(_background_node_tasks) > 0, (
                    "CRITICAL REGRESSION: _background_node_tasks was cleared on User A disconnect!"
                )

                # 2. None of the tasks in the set were cancelled
                for t in _background_node_tasks:
                    assert not t.cancelled(), (
                        "CRITICAL REGRESSION: User B (or A) task was cancelled when User A disconnected!"
                    )

                # 3. User B is still connected and can send another turn
                await ws_b.send_json(
                    {
                        "type": "chat_message",
                        "session_id": "session_b",
                        "content": "User B second message",
                    }
                )
                b_received_frames = []
                while True:
                    f = await ws_b.receive_json()
                    b_received_frames.append(f)
                    if f.get("type") == "stream_end":
                        break
                assert any(f.get("type") == "stream_start" for f in b_received_frames)

                # Wait for all background tasks to finish
                await asyncio.sleep(0.6)

                assert task_results["user_alpha"] is True, "User A's background task failed to complete"
                assert task_results["user_beta"] is True, "User B's background task failed to complete"

                await ws_b.disconnect()

    # Wait for any lingering second-turn task to self-discard
    await asyncio.sleep(0.6)
    assert len(_background_node_tasks) == 0, (
        f"Tasks remained in set after completion: {len(_background_node_tasks)}"
    )


# ==============================================================================
# 3. High-Concurrency Burst Disconnect Simulation
# ==============================================================================


@pytest.mark.asyncio
async def test_burst_disconnect_concurrency_isolation(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Stress-test 6 concurrent clients: 3 disconnect abruptly while tasks are in flight.

    Verify that:
    - All 6 background tasks finish executing and are not cancelled.
    - Remaining 3 clients continue operating without interference.
    - Set drains cleanly to 0.
    """
    _background_node_tasks.clear()
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    num_users = 6
    user_tokens = []
    async with session_factory() as session:
        for i in range(num_users):
            _, tok = await _create_test_user(
                session, f"burst_user_{i}", f"burst_user_{i}", f"burst_{i}@test.com"
            )
            user_tokens.append(tok)

    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: storage

    completed_extractions: set[str] = set()

    async def concurrent_worker(user_id: str, *args: Any, **kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.3)
        completed_extractions.add(user_id)
        return []

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in ["Burst ", "ok."]:
            yield chunk

    with patch("tars.api.routers.chat.get_session_factory", return_value=session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker, "extract_and_sync", side_effect=concurrent_worker
            ):
                clients = [
                    AsyncASGIWebSocket(app, "/api/v1/chat/ws", f"token={user_tokens[i]}")
                    for i in range(num_users)
                ]

                for c in clients:
                    await c.connect()

                # Dispatch turns across all 6 clients concurrently
                async def run_turn(client: AsyncASGIWebSocket, uid: str) -> None:
                    await client.send_json(
                        {"type": "chat_message", "session_id": f"s_{uid}", "content": "ping"}
                    )
                    while True:
                        f = await client.receive_json()
                        if f.get("type") == "stream_end":
                            break

                await asyncio.gather(
                    *[run_turn(clients[i], f"burst_user_{i}") for i in range(num_users)]
                )

                assert len(_background_node_tasks) == num_users, (
                    f"Expected {num_users} active tasks, got {len(_background_node_tasks)}"
                )

                # Disconnect clients 0, 1, 2 abruptly
                disconnect_coros = [clients[i].disconnect(code=1001) for i in range(3)]
                await asyncio.gather(*disconnect_coros)

                # Verify tasks are NOT cancelled
                assert len(_background_node_tasks) == num_users
                for t in _background_node_tasks:
                    assert not t.cancelled()

                # Remaining clients 3, 4, 5 execute another turn successfully
                for i in range(3, num_users):
                    await clients[i].send_json(
                        {"type": "chat_message", "session_id": f"s_{i}", "content": "ping2"}
                    )
                    while True:
                        f = await clients[i].receive_json()
                        if f.get("type") == "stream_end":
                            break

                # Disconnect remaining clients
                for i in range(3, num_users):
                    await clients[i].disconnect()

                # Wait for all extractions to complete
                await asyncio.sleep(0.7)

                for i in range(num_users):
                    assert f"burst_user_{i}" in completed_extractions

    await asyncio.sleep(0.5)
    assert len(_background_node_tasks) == 0


# ==============================================================================
# 4. Lifespan Graceful Shutdown Draining & Timeout Testing
# ==============================================================================


@pytest.mark.asyncio
async def test_shutdown_background_tasks_graceful_drain_and_timeout() -> None:
    """Empirically test shutdown_background_tasks under various task states:

    1. Empty set -> returns immediately.
    2. Fast tasks (< timeout) -> finish cleanly without cancellation.
    3. Slow tasks (> timeout) -> cancelled cleanly after timeout without unhandled errors.
    4. Tasks that raise exceptions -> gathered safely without crashing shutdown.
    5. Clean set clear -> set is empty after shutdown.
    """
    _background_node_tasks.clear()

    # 1. Empty set
    await shutdown_background_tasks(timeout=1.0)
    assert len(_background_node_tasks) == 0

    # 2. Fast tasks
    fast_completed = False

    async def fast_coro() -> None:
        nonlocal fast_completed
        await asyncio.sleep(0.05)
        fast_completed = True

    t_fast = asyncio.create_task(fast_coro())
    _background_node_tasks.add(t_fast)
    t_fast.add_done_callback(_background_node_tasks.discard)

    await shutdown_background_tasks(timeout=1.0)
    assert fast_completed is True
    assert t_fast.done()
    assert not t_fast.cancelled()
    assert len(_background_node_tasks) == 0

    # 3. Slow tasks exceeding timeout
    slow_started = False

    async def slow_coro() -> None:
        nonlocal slow_started
        slow_started = True
        await asyncio.sleep(10.0)

    t_slow = asyncio.create_task(slow_coro())
    _background_node_tasks.add(t_slow)
    t_slow.add_done_callback(_background_node_tasks.discard)

    await shutdown_background_tasks(timeout=0.1)
    assert slow_started is True
    assert t_slow.done()
    assert t_slow.cancelled(), "Slow task should have been cancelled after timeout"
    assert len(_background_node_tasks) == 0

    # 4. Faulty task raising exception during shutdown
    async def faulty_coro() -> None:
        await asyncio.sleep(0.05)
        raise RuntimeError("Simulated failure during shutdown")

    t_faulty = asyncio.create_task(faulty_coro())
    _background_node_tasks.add(t_faulty)
    t_faulty.add_done_callback(_background_node_tasks.discard)

    # Must not raise RuntimeError to the caller
    await shutdown_background_tasks(timeout=0.5)
    assert t_faulty.done()
    assert len(_background_node_tasks) == 0
