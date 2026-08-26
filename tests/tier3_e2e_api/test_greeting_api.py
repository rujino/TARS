"""Tier 3 E2E API Tests: Proactive Greeting & Smart Session Lifecycle (/api/v1/chat/greeting, /api/v1/chat/stream).

Verifies:
1. Proactive Greeting Handshake:
   - 401 Unauthorized for unauthenticated requests.
   - 200 OK with valid GreetingResponse schema for authenticated users.
   - Timezone parameter handling ("Asia/Seoul", "America/New_York").
   - TARS Persona mode reflections (companion vs work).
   - Session binding and idle gap tracking.
2. Full SSE Streaming with Smart Session Lifecycle:
   - Multi-turn conversation persistence and session continuity.
   - Natural language session reset via SSE stream.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.router import HybridLLMRouter
from tars.db.models import ChatMessage, ChatSession, TARSSettings, User

# ============================================================================
# 1. Proactive Greeting API Tests
# ============================================================================


@pytest.mark.asyncio
async def test_greeting_unauthenticated_returns_401(
    api_client: AsyncClient,
) -> None:
    """Verify GET /api/v1/chat/greeting rejects unauthenticated requests."""
    response = await api_client.get("/api/v1/chat/greeting")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_greeting_authenticated_success_response(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify GET /api/v1/chat/greeting returns 200 with GreetingResponse schema."""
    with patch.object(
        HybridLLMRouter,
        "route_and_generate",
        return_value="시스템 진단 완료. 대기 모드를 해제하고 파트너의 명령을 기다리고 있습니다.",
    ):
        response = await auth_client.get("/api/v1/chat/greeting")
        assert response.status_code == 200

        data = response.json()
        assert "greeting" in data
        assert isinstance(data["greeting"], str)
        assert len(data["greeting"]) > 0
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert data["mode"] == "companion"
        assert "idle_seconds" in data
        assert isinstance(data["idle_seconds"], int)


@pytest.mark.asyncio
async def test_greeting_with_timezone_parameters(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify timezone parameter is accepted and processed without error."""
    with patch.object(
        HybridLLMRouter,
        "route_and_generate",
        return_value="시간대 동기화 완료. 대기 중입니다, 파트너.",
    ):
        # Test Seoul Timezone
        res_seoul = await auth_client.get("/api/v1/chat/greeting?timezone=Asia/Seoul")
        assert res_seoul.status_code == 200
        assert len(res_seoul.json()["greeting"]) > 0

        # Test New York Timezone
        res_ny = await auth_client.get("/api/v1/chat/greeting?timezone=America/New_York")
        assert res_ny.status_code == 200
        assert len(res_ny.json()["greeting"]) > 0


@pytest.mark.asyncio
async def test_greeting_reflects_work_mode(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
    seed_test_user: User,
) -> None:
    """Verify work mode produces tactical, serious greeting."""
    # Update settings to work mode
    stmt = select(TARSSettings).where(TARSSettings.user_id == seed_test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    settings.mode = "work"
    settings.humor_level = 0.0
    await async_db_session.commit()

    with patch.object(
        HybridLLMRouter,
        "route_and_generate",
        return_value="TARS 시스템 점검 완료. 작업 지시를 입력하십시오.",
    ):
        response = await auth_client.get("/api/v1/chat/greeting")
        assert response.status_code == 200

        data = response.json()
        assert data["mode"] == "work"
        # Fallback or LLM greeting in work mode is disciplined
        assert any(
            kw in data["greeting"]
            for kw in ["시스템", "모듈", "작업", "명령", "대기", "가동", "점검"]
        )


# ============================================================================
# 2. SSE Streaming with Smart Session Lifecycle Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sse_streaming_smart_session_multi_turn(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
    seed_test_user: User,
) -> None:
    """Verify multi-turn chat over SSE persists conversation and preserves session_id."""
    mock_tokens = ["TARS: ", "Atmospheric ", "pressure ", "is ", "nominal."]

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
        # --- Turn 1: Initial query ---
        payload_1 = {
            "session_id": "default_session",
            "message": "TARS, report atmospheric condition.",
        }
        res_1 = await auth_client.post("/api/v1/chat/stream", json=payload_1)
        assert res_1.status_code == 200

        lines_1 = res_1.text.strip().split("\n")
        session_id = None
        for line in lines_1:
            if line.startswith("event: stream_start"):
                continue
            if line.startswith("data: {"):
                data = json.loads(line[6:])
                if "session_id" in data:
                    session_id = data["session_id"]
                    break

        assert session_id is not None
        assert session_id != "default_session"

        # Verify session and messages in DB
        stmt_session = select(ChatSession).where(ChatSession.id == session_id)
        res_session = await async_db_session.execute(stmt_session)
        db_session = res_session.scalar_one_or_none()
        assert db_session is not None
        assert db_session.user_id == seed_test_user.id
        assert len(db_session.messages) == 2

        # --- Turn 2: Follow-up query in same session ---
        payload_2 = {
            "session_id": session_id,
            "message": "And what about radiation levels?",
        }
        res_2 = await auth_client.post("/api/v1/chat/stream", json=payload_2)
        assert res_2.status_code == 200

        lines_2 = res_2.text.strip().split("\n")
        session_id_2 = None
        for line in lines_2:
            if line.startswith("data: {"):
                data = json.loads(line[6:])
                if "session_id" in data:
                    session_id_2 = data["session_id"]
                    break

        # Same session ID is maintained
        assert session_id_2 == session_id

        # Total turns in DB is now 4 messages (2 user + 2 assistant)
        stmt_msgs = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        res_msgs = await async_db_session.execute(stmt_msgs)
        messages = res_msgs.scalars().all()
        assert len(messages) == 4


@pytest.mark.asyncio
async def test_sse_streaming_natural_reset_command(
    auth_client: AsyncClient,
    async_db_session: AsyncSession,
    seed_test_user: User,
) -> None:
    """Verify natural language reset command in SSE resets session and returns confirmation."""
    # First establish a session
    mock_tokens = ["Initial ", "response."]

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for t in mock_tokens:
            yield t

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
        res_init = await auth_client.post(
            "/api/v1/chat/stream",
            json={"session_id": "default_session", "message": "First task."},
        )
        assert res_init.status_code == 200

        # Send Reset Command
        payload_reset = {
            "session_id": "default_session",
            "message": "TARS, 리셋해줘",
        }
        res_reset = await auth_client.post("/api/v1/chat/stream", json=payload_reset)
        assert res_reset.status_code == 200

        reset_body = res_reset.text
        assert "초기화" in reset_body or "아카이브" in reset_body or "리셋" in reset_body
        assert "stream_end" in reset_body
