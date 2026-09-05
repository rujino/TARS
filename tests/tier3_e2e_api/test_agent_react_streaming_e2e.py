"""Tier 3 E2E Integration Tests: Real-time ReAct Agent Tool Calling & Streaming via SSE & WebSocket.

Verifies:
1. SSE ReAct Tool Execution: tool_start -> tool_result -> token -> stream_end with tools_used.
2. WebSocket ReAct Tool Execution: tool_start frame -> tool_result frame -> token frames -> stream_end.
3. Tool Error Resilience: Graceful fallback when a tool throws during streaming turn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from tars.adapters.base import LLMResponse, ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_db_session, get_storage_manager, get_tool_registry
from tars.storage.manager import FileStorageManager
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import GoogleCalendarAdapter
from tars.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_sse_agent_react_tool_calling_stream(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify end-to-end ReAct tool calling events emitted through SSE /stream."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    calendar_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    registry = ToolRegistry(calendar_adapter.get_tools())

    app.dependency_overrides[get_db_session] = lambda: test_session_factory()
    app.dependency_overrides[get_storage_manager] = lambda: storage
    app.dependency_overrides[get_tool_registry] = lambda: registry

    # Mock LLM: Turn 1 requests tool call, Turn 2 gives final answer with tool result
    turn1_resp = LLMResponse(
        content="Checking calendar now, Cooper.",
        tool_calls=[
            ToolCallData(
                id="call_cal_001",
                name="calendar_list_events",
                arguments={"max_results": 2},
            )
        ],
    )
    turn2_resp = LLMResponse(
        content="You have the Endurance Mission Briefing scheduled at 10:00 UTC, partner.",
        tool_calls=[],
    )

    call_count = 0

    async def mock_generate_response(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return turn1_resp
        return turn2_resp

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_generate_response", side_effect=mock_generate_response):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {test_user_token}"},
            ) as client:
                resp = await client.post(
                    "/api/v1/chat/stream",
                    json={
                        "message": "What is my flight schedule today?",
                        "session_id": "test_agent_react_session",
                    },
                )

                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
                body = resp.text

                # Verify event sequence
                assert "event: stream_start" in body
                assert "event: tool_start" in body
                assert "event: tool_result" in body
                assert "event: token" in body
                assert "event: stream_end" in body
                assert "event: done" in body

                # Verify tool specifics
                assert "calendar_list_events" in body
                assert "Endurance Mission Briefing" in body
                assert "partner" in body


def test_websocket_agent_react_tool_calling_stream(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify end-to-end ReAct tool calling frames emitted through WebSocket /ws."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    calendar_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    registry = ToolRegistry(calendar_adapter.get_tools())

    app.dependency_overrides[get_storage_manager] = lambda: storage
    app.dependency_overrides[get_tool_registry] = lambda: registry

    turn1_resp = LLMResponse(
        content="Accessing mission schedule.",
        tool_calls=[
            ToolCallData(
                id="call_cal_ws_1",
                name="calendar_list_events",
                arguments={"max_results": 1},
            )
        ],
    )
    turn2_resp = LLMResponse(
        content="Mission sync briefing confirmed on schedule.",
        tool_calls=[],
    )

    call_count = 0

    async def mock_generate_response(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return turn1_resp
        return turn2_resp

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch("tars.services.agent_chat.get_session_factory", return_value=test_session_factory):
            with patch("tars.extractor.worker.SelfEvolvingKnowledgeWorker.extract_and_sync", new_callable=AsyncMock):
                with patch.object(HybridLLMRouter, "route_and_generate_response", side_effect=mock_generate_response):
                    with TestClient(app) as client:
                        with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                            ws.send_json(
                                {
                                    "type": "chat_message",
                                    "content": "Check my schedule via WS.",
                                    "session_id": "ws_react_session",
                                }
                            )

                            received_frames = []
                            while True:
                                frame = ws.receive_json()
                                received_frames.append(frame)
                                if frame.get("type") == "stream_end":
                                    break

                            frame_types = [f["type"] for f in received_frames]
                            assert "stream_start" in frame_types
                            assert "tool_start" in frame_types
                            assert "tool_result" in frame_types
                            assert "token" in frame_types
                            assert "stream_end" in frame_types

                            # Check tool_start details
                            tool_start_frame = next(f for f in received_frames if f["type"] == "tool_start")
                            assert tool_start_frame["tool"] == "calendar_list_events"

                            # Check tool_result details
                            tool_result_frame = next(f for f in received_frames if f["type"] == "tool_result")
                            assert tool_result_frame["status"] == "success"
                            assert tool_result_frame["tool"] == "calendar_list_events"

                            # Check stream_end details
                            end_frame = next(f for f in received_frames if f["type"] == "stream_end")
                            assert "calendar_list_events" in end_frame["tools_used"]
                            assert "Mission sync briefing" in end_frame["content"]


@pytest.mark.asyncio
async def test_agent_tool_error_graceful_handling(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify tool failure triggers tool_result(error) and graceful TARS response generation."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Tool that deliberately fails
    failing_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    failing_adapter.list_events = AsyncMock(side_effect=RuntimeError("Google API 503 Service Unavailable"))
    registry = ToolRegistry(failing_adapter.get_tools())

    app.dependency_overrides[get_db_session] = lambda: test_session_factory()
    app.dependency_overrides[get_storage_manager] = lambda: storage
    app.dependency_overrides[get_tool_registry] = lambda: registry

    turn1_resp = LLMResponse(
        content="Querying calendar.",
        tool_calls=[ToolCallData(id="call_fail", name="calendar_list_events", arguments={})],
    )
    turn2_resp = LLMResponse(
        content="Calendar telemetry offline. Suggest manual schedule verification, Cooper.",
        tool_calls=[],
    )

    call_count = 0

    async def mock_generate_response(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return turn1_resp
        return turn2_resp

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_generate_response", side_effect=mock_generate_response):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": f"Bearer {test_user_token}"},
            ) as client:
                resp = await client.post(
                    "/api/v1/chat/stream",
                    json={
                        "message": "Check schedule with failing API.",
                        "session_id": "test_error_session",
                    },
                )

                assert resp.status_code == 200
                body = resp.text
                assert "event: tool_start" in body
                assert "event: tool_result" in body
                assert "error" in body
                assert "Calendar telemetry offline" in body
