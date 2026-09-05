"""Tier 3 E2E API Tests: WebSocket Real-Time Bidirectional Token Streaming (/api/v1/chat/ws).

Verifies:
1. Authentication Handshake:
   - Rejects missing or invalid JWT tokens with WebSocket close code 4001 / 1008.
   - Accepts valid JWT tokens in query parameter (?token=...).
2. Bidirectional Streaming Protocol:
   - Client sends JSON frame: {"type": "chat_message", "session_id": "...", "content": "..."}.
   - Server responds with structured event sequence:
     1. stream_start
     2. token (multiple delta frames)
     3. stream_end (with full accumulated response)
3. Lifecycle Events & Session Continuity:
   - Multiple sequential turns in a single persistent WebSocket connection.
4. Error Handling & Malformed Payloads:
   - Handles corrupted JSON without crashing server process.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app, lifespan
from tars.api.dependencies import get_storage_manager
from tars.core.security import create_access_token
from tars.db.models import User
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.orchestrator.nodes import _background_node_tasks, shutdown_background_tasks
from tars.storage.manager import FileStorageManager

# ============================================================================
# 1. WebSocket Authentication Handshake Tests
# ============================================================================


def test_websocket_auth_rejects_missing_token() -> None:
    """Verify WebSocket connection without token query parameter is closed immediately."""
    app = create_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/chat/ws"):
            pass

    assert exc_info.value.code in (4001, 1008, 4003)


def test_websocket_auth_rejects_invalid_token() -> None:
    """Verify WebSocket connection with forged JWT token is closed with policy violation."""
    app = create_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/chat/ws?token=invalid.jwt.signature"):
            pass

    assert exc_info.value.code in (4001, 1008, 4003)


# ============================================================================
# 2. Real-Time Token Streaming Over WebSocket
# ============================================================================


def test_websocket_streaming_full_lifecycle(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    temp_storage_root: Any,
) -> None:
    """Verify bidirectional message exchange and full token streaming lifecycle."""
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    client = TestClient(app)

    # Mock the LLM router streaming output
    mock_tokens = ["TARS: ", "Atmospheric ", "pressure ", "is ", "normal."]

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch("tars.api.routers.chat._execute_background_knowledge_extraction"):
                with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as websocket:
                    # 1. Send chat message
                    send_payload = {
                        "type": "chat_message",
                        "session_id": "session_ws_001",
                        "content": "TARS, check atmosphere.",
                    }
                    websocket.send_json(send_payload)

                    # 2. Collect incoming frames
                    received_frames: list[dict[str, Any]] = []
                    while True:
                        data = websocket.receive_json()
                        received_frames.append(data)
                        if data.get("type") == "stream_end" or data.get("event") == "stream_end":
                            break

                    # 3. Validate lifecycle sequence
                    event_types = [f.get("type") or f.get("event") for f in received_frames]
                    assert "stream_start" in event_types
                    assert "token" in event_types
                    assert "stream_end" in event_types

                    # Verify tokens reconstruct original output
                    token_frames = [
                        f.get("content") or f.get("delta") or f.get("data", {}).get("content", "")
                        for f in received_frames
                        if (f.get("type") or f.get("event")) == "token"
                    ]
                    assert "".join(token_frames) == "TARS: Atmospheric pressure is normal."


# ============================================================================
# 3. Multi-Turn Streaming over Single WebSocket Connection
# ============================================================================


def test_websocket_multi_turn_in_single_connection(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    temp_storage_root: Any,
) -> None:
    """Verify that multiple consecutive chat turns can be executed in the same connection."""
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    client = TestClient(app)

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream") as mock_router_stream:
            # Define turn 1 response
            async def turn1_stream(*args: Any, **kwargs: Any) -> Any:
                for t in ["Response ", "One."]:
                    yield t

            # Define turn 2 response
            async def turn2_stream(*args: Any, **kwargs: Any) -> Any:
                for t in ["Response ", "Two."]:
                    yield t

            mock_router_stream.side_effect = [turn1_stream(), turn2_stream()]

            with patch("tars.api.routers.chat._execute_background_knowledge_extraction"):
                with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                    # --- Turn 1 ---
                    ws.send_json(
                        {"type": "chat_message", "session_id": "multi_ws", "content": "Turn 1"}
                    )
                    frames_turn1 = []
                    while True:
                        f = ws.receive_json()
                        frames_turn1.append(f)
                        if (f.get("type") or f.get("event")) == "stream_end":
                            break
                    assert any(
                        (f.get("type") or f.get("event")) == "stream_start" for f in frames_turn1
                    )

                    # --- Turn 2 ---
                    ws.send_json(
                        {"type": "chat_message", "session_id": "multi_ws", "content": "Turn 2"}
                    )
                    frames_turn2 = []
                    while True:
                        f = ws.receive_json()
                        frames_turn2.append(f)
                        if (f.get("type") or f.get("event")) == "stream_end":
                            break
                    assert any(
                        (f.get("type") or f.get("event")) == "stream_start" for f in frames_turn2
                    )




# ============================================================================
# 4. Malformed Frame & Error Handling
# ============================================================================


def test_websocket_handles_malformed_json(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
) -> None:
    """Verify sending non-JSON or invalid schema sends an error frame without closing connection."""
    app = create_app()
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    client = TestClient(app)

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
            ws.send_text("MALFORMED_NON_JSON_STRING")
            frame = ws.receive_json()
            assert frame.get("type") == "error" or frame.get("event") == "error"
            assert "message" in frame or "error" in frame


# ============================================================================
# 5. WebSocket Disconnection Resilience & Background Task Preservation
# ============================================================================


def test_websocket_disconnect_preserves_background_tasks(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    temp_storage_root: Any,
) -> None:
    """Verify disconnecting client does NOT cancel or interrupt background extraction tasks."""
    _background_node_tasks.clear()
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    task_started = threading.Event()
    allow_finish = threading.Event()
    task_completed = threading.Event()

    async def slow_extract_and_sync(*args: Any, **kwargs: Any) -> list[Any]:
        task_started.set()
        try:
            while not allow_finish.is_set():
                await asyncio.sleep(0.01)
            task_completed.set()
            return [{"okf_id": "test_resilience_okf"}]
        except asyncio.CancelledError:
            raise

    mock_tokens = ["TARS: ", "Navigation ", "locked."]

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch("tars.services.agent_chat.get_session_factory", return_value=test_session_factory):
            with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
                with patch.object(
                    SelfEvolvingKnowledgeWorker,
                    "extract_and_sync",
                    side_effect=slow_extract_and_sync,
                ):
                    with TestClient(app) as client:
                        with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                            ws.send_json(
                                {
                                    "type": "chat_message",
                                    "session_id": "session_disconnect_test",
                                    "content": "Begin trajectory analysis.",
                                }
                            )

                            while True:
                                frame = ws.receive_json()
                                if frame.get("type") == "stream_end" or frame.get("event") == "stream_end":
                                    break

                            assert task_started.wait(timeout=2.0), "Background task did not start"
                            pending_tasks = [t for t in _background_node_tasks if not t.done()]
                            assert len(pending_tasks) >= 1, "No active background task in _background_node_tasks"
                            bg_task = pending_tasks[0]

                        # --- WebSocket is now disconnected (exited context) ---
                        # Verify background task is NOT cancelled and continues executing
                        assert not bg_task.cancelled(), "Background task was unexpectedly cancelled on WS disconnect"
                        assert not bg_task.done(), "Background task prematurely terminated"

                        # Allow task to complete
                        allow_finish.set()
                        assert task_completed.wait(timeout=2.0), "Background task did not finish execution"

                        # Wait for task completion
                        timeout_at = time.time() + 2.0
                        while not bg_task.done() and time.time() < timeout_at:
                            time.sleep(0.01)

                        assert bg_task.done(), "Background task is not done"
                        assert not bg_task.cancelled(), "Background task was marked cancelled after completion"

                        # Wait for done callback to discard task from set
                        timeout_at = time.time() + 2.0
                        while bg_task in _background_node_tasks and time.time() < timeout_at:
                            time.sleep(0.01)
                        assert bg_task not in _background_node_tasks


# ============================================================================
# 6. Multi-User Concurrency Isolation
# ============================================================================


def test_websocket_multi_user_background_isolation(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    seed_second_user: User,
    temp_storage_root: Any,
) -> None:
    """Verify User A disconnecting does not cancel or clear User B's active background tasks."""
    _background_node_tasks.clear()
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    token_b = create_access_token(data={"sub": seed_second_user.id})

    task_b_started = threading.Event()
    allow_b_finish = threading.Event()
    task_b_completed = threading.Event()

    async def mock_extract_and_sync(
        worker_self: Any,
        user_id: str,
        conversation_turns: Any,
        db_session: Any,
    ) -> list[Any]:
        if user_id == seed_second_user.id:
            task_b_started.set()
            try:
                while not allow_b_finish.is_set():
                    await asyncio.sleep(0.01)
                task_b_completed.set()
            except asyncio.CancelledError:
                raise
        return []

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        yield "Response acknowledged."

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch("tars.services.agent_chat.get_session_factory", return_value=test_session_factory):
            with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
                with patch.object(
                    SelfEvolvingKnowledgeWorker,
                    "extract_and_sync",
                    autospec=True,
                    side_effect=mock_extract_and_sync,
                ):
                    with TestClient(app) as client:
                        # 1. User B connects and initiates background extraction
                        with client.websocket_connect(f"/api/v1/chat/ws?token={token_b}") as ws_b:
                            ws_b.send_json(
                                {
                                    "type": "chat_message",
                                    "session_id": "session_user_b",
                                    "content": "User B message",
                                }
                            )
                            while True:
                                f = ws_b.receive_json()
                                if f.get("type") == "stream_end" or f.get("event") == "stream_end":
                                    break

                            assert task_b_started.wait(timeout=2.0), "User B task did not start"
                            pending_b = [t for t in _background_node_tasks if not t.done()]
                            assert len(pending_b) >= 1, "User B task not found in _background_node_tasks"
                            task_b = pending_b[0]

                            # 2. User A connects concurrently while User B's task is in flight
                            with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws_a:
                                ws_a.send_json(
                                    {
                                        "type": "chat_message",
                                        "session_id": "session_user_a",
                                        "content": "User A message",
                                    }
                                )
                                while True:
                                    f = ws_a.receive_json()
                                    if f.get("type") == "stream_end" or f.get("event") == "stream_end":
                                        break

                            # 3. User A has exited and disconnected.
                            # In AS-IS, User A's finally block wiped and cancelled all background tasks.
                            # Verify User B's task remains untouched and active:
                            assert not task_b.cancelled(), "User B task was cancelled by User A disconnect!"
                            assert not task_b.done(), "User B task was prematurely stopped"
                            assert task_b in _background_node_tasks, "User B task was cleared from _background_node_tasks!"

                            # 4. User B's task is signaled to finish
                            allow_b_finish.set()
                            assert task_b_completed.wait(timeout=2.0), "User B task failed to complete"

                            timeout_at = time.time() + 2.0
                            while not task_b.done() and time.time() < timeout_at:
                                time.sleep(0.01)

                            assert task_b.done(), "User B task is not done"
                            assert not task_b.cancelled(), "User B task was cancelled"


# ============================================================================
# 7. Lifespan Graceful Shutdown Lifecycle Tests
# ============================================================================


@pytest.mark.asyncio
async def test_shutdown_background_tasks_lifecycle() -> None:
    """Verify shutdown_background_tasks awaits fast tasks, handles empty/done, and cancels timed-out tasks."""
    _background_node_tasks.clear()

    # 1. Empty set returns immediately
    await shutdown_background_tasks(timeout=1.0)
    assert len(_background_node_tasks) == 0

    # 2. Normal completion of tasks within timeout
    fast_completed = False

    async def fast_task() -> None:
        nonlocal fast_completed
        await asyncio.sleep(0.02)
        fast_completed = True

    t_fast = asyncio.create_task(fast_task())
    _background_node_tasks.add(t_fast)
    t_fast.add_done_callback(_background_node_tasks.discard)

    await shutdown_background_tasks(timeout=1.0)
    assert fast_completed is True
    assert t_fast.done()
    assert not t_fast.cancelled()
    assert len(_background_node_tasks) == 0

    # 3. Handling tasks already marked done
    async def noop() -> None:
        pass

    t_noop = asyncio.create_task(noop())
    await t_noop
    _background_node_tasks.add(t_noop)
    await shutdown_background_tasks(timeout=1.0)
    assert len(_background_node_tasks) == 0

    # 4. Cancelling hanging tasks exceeding timeout
    was_cancelled = False

    async def hanging_task() -> None:
        nonlocal was_cancelled
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    t_hang = asyncio.create_task(hanging_task())
    _background_node_tasks.add(t_hang)
    t_hang.add_done_callback(_background_node_tasks.discard)

    await shutdown_background_tasks(timeout=0.05)
    assert t_hang.done()
    assert t_hang.cancelled()
    assert was_cancelled is True
    assert len(_background_node_tasks) == 0


@pytest.mark.asyncio
async def test_lifespan_graceful_shutdown_drains_tasks(test_engine: AsyncEngine) -> None:
    """Verify FastAPI lifespan cleanly invokes shutdown_background_tasks and drains tasks during shutdown."""
    _background_node_tasks.clear()
    app = create_app()

    # 1. Verify lifespan calls shutdown_background_tasks(timeout=5.0)
    with patch("tars.api.app.shutdown_background_tasks", new_callable=AsyncMock) as mock_shutdown:
        async with lifespan(app):
            mock_shutdown.assert_not_called()
        mock_shutdown.assert_awaited_once_with(timeout=5.0)

    # 2. End-to-end drain test: active background task is drained when lifespan exits
    task_finished = False

    async def active_task() -> None:
        nonlocal task_finished
        await asyncio.sleep(0.05)
        task_finished = True

    t = asyncio.create_task(active_task())
    _background_node_tasks.add(t)
    t.add_done_callback(_background_node_tasks.discard)

    async with lifespan(app):
        assert not t.done() or task_finished

    assert task_finished is True
    assert t.done()
    assert not t.cancelled()
    assert len(_background_node_tasks) == 0


# Backward compatibility aliases for test discovery suites
test_websocket_disconnect_resilience_background_task_completes = (
    test_websocket_disconnect_preserves_background_tasks
)
test_websocket_multi_user_concurrency_isolation = (
    test_websocket_multi_user_background_isolation
)
test_lifespan_graceful_shutdown_integration = (
    test_lifespan_graceful_shutdown_drains_tasks
)

