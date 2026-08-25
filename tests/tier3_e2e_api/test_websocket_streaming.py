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

from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_storage_manager
from tars.db.models import User
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

            with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                # --- Turn 1 ---
                ws.send_json({"type": "chat_message", "session_id": "multi_ws", "content": "Turn 1"})
                frames_turn1 = []
                while True:
                    f = ws.receive_json()
                    frames_turn1.append(f)
                    if (f.get("type") or f.get("event")) == "stream_end":
                        break
                assert any((f.get("type") or f.get("event")) == "stream_start" for f in frames_turn1)

                # --- Turn 2 ---
                ws.send_json({"type": "chat_message", "session_id": "multi_ws", "content": "Turn 2"})
                frames_turn2 = []
                while True:
                    f = ws.receive_json()
                    frames_turn2.append(f)
                    if (f.get("type") or f.get("event")) == "stream_end":
                        break
                assert any((f.get("type") or f.get("event")) == "stream_start" for f in frames_turn2)


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
