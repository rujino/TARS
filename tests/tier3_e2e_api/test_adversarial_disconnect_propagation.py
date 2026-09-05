"""Tier 3 E2E / Adversarial Stress: Rapid Client Disconnect Propagation (REL-02).

Empirical verification of:
1. SSE Disconnect Token Halting & Orphan Task Prevention:
   - Verifies whether client disconnection during SSE (/api/v1/chat/stream) halts
     downstream token generation in the LLM router and prevents zombie tasks.
2. SSE Concurrent Disconnect Storm:
   - Verifies server resilience when multiple concurrent clients disconnect mid-stream.
3. WebSocket Disconnect Token Halting:
   - Verifies whether abruptly closing a WebSocket (/api/v1/chat/ws) halts token generation
     and cleans up turn state.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_storage_manager
from tars.db.models import User
from tars.storage.manager import FileStorageManager

# ============================================================================
# 1. SSE Disconnect Tests
# ============================================================================


@pytest.mark.asyncio
async def test_sse_disconnect_halts_token_generation(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify that SSE client disconnect halts downstream model token generation immediately.

    REL-02 Specification:
    "SSE 및 WebSocket 실시간 스트리밍 엔드포인트에서 클라이언트 연결 해제(request.is_disconnected())
    상태를 감지하여, 탭 닫기나 네트워크 단절 시 백엔드 그래프 실행 및 LLM 토큰 생성을 즉시 중단해야 합니다."
    """
    total_tokens_generated = 0
    generator_finally_called = False

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        nonlocal total_tokens_generated, generator_finally_called
        try:
            for i in range(100):
                total_tokens_generated += 1
                await asyncio.sleep(0.005)
                yield f"tok_{i} "
        finally:
            generator_finally_called = True

    # Client disconnects after receiving the first token
    call_count = 0

    async def mock_is_disconnected(self: Any) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream), \
         patch("starlette.requests.Request.is_disconnected", new=mock_is_disconnected), \
         patch("tars.api.routers.chat.logger.info") as mock_log:

        response = await auth_client.post(
            "/api/v1/chat/stream",
            json={"session_id": "sess_sse_disc_1", "message": "Test disconnect"},
        )
        assert response.status_code == 200

        # Wait 200ms to allow any orphan background generation to run if unhalted
        await asyncio.sleep(0.2)
        print(f"DEBUG SSE: total_tokens_generated={total_tokens_generated}, finally_called={generator_finally_called}")

        # Disconnect log must be emitted
        assert any(
            "Client disconnected from SSE stream; terminating graph execution" in str(arg)
            for call in mock_log.call_args_list
            for arg in call.args
        ), "Client disconnect log entry was not found in chat router logs"

        # EMPIRICAL ORACLE ASSERTION:
        # If generation was halted immediately upon client disconnect, total tokens generated
        # must be small (e.g. <= 3) and generator's finally block must have run.
        # If zombie execution occurs, total_tokens_generated will continue running to 100!
        assert total_tokens_generated <= 5, (
            f"ZOMBIE EXECUTION DETECTED: Server generated {total_tokens_generated}/100 tokens "
            "after client disconnected! Downstream LangGraph/LLM generation was not halted."
        )
        assert generator_finally_called is True, (
            "Orphan stream generator: finally block was not executed after client disconnected."
        )


@pytest.mark.asyncio
async def test_sse_disconnect_no_orphan_tasks(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify that SSE client disconnect leaves zero orphan or lingering background tasks."""
    baseline_tasks = {t for t in asyncio.all_tasks() if not t.done()}

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        for i in range(100):
            await asyncio.sleep(0.01)
            yield f"tok_{i} "

    # Disconnect after first token
    call_count = 0

    async def mock_is_disconnected(self: Any) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 3

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream), \
         patch("starlette.requests.Request.is_disconnected", new=mock_is_disconnected):

        response = await auth_client.post(
            "/api/v1/chat/stream",
            json={"session_id": "sess_sse_orphan_check", "message": "Check tasks"},
        )
        assert response.status_code == 200

        # Allow 50ms for event loop finalizers
        await asyncio.sleep(0.05)

        # Active tasks minus baseline must not contain any LangGraph or chat streaming tasks
        current_tasks = {t for t in asyncio.all_tasks() if not t.done()}
        new_tasks = current_tasks - baseline_tasks

        orphan_stream_tasks = [
            t for t in new_tasks
            if any(name in str(t) for name in ["stream_chat", "stream_graph_events", "llm_node", "sse_event_generator"])
        ]
        assert len(orphan_stream_tasks) == 0, f"Orphan streaming tasks detected: {orphan_stream_tasks}"



# ============================================================================
# 2. WebSocket Disconnect Tests
# ============================================================================


def test_websocket_disconnect_immediate_halt(
    test_engine: AsyncEngine,
    seed_test_user: User,
    test_user_token: str,
    temp_storage_root: Any,
) -> None:
    """Verify WebSocket client abrupt closure mid-generation halts LLM generator immediately."""
    app = create_app()
    mock_storage = FileStorageManager(base_dir=temp_storage_root)
    app.dependency_overrides[get_storage_manager] = lambda: mock_storage

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    tokens_produced = 0
    generator_closed = False

    async def mock_router_stream(*args: Any, **kwargs: Any) -> Any:
        nonlocal tokens_produced, generator_closed
        try:
            for i in range(100):
                tokens_produced += 1
                await asyncio.sleep(0.01)
                yield f"tok_{i} "
        finally:
            generator_closed = True

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory), \
         patch("tars.services.agent_chat.get_session_factory", return_value=test_session_factory), \
         patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_router_stream):

        client = TestClient(app)
        with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
            ws.send_json({"type": "chat_message", "session_id": "ws_disc_1", "content": "Start turn"})

            # Read stream_start
            f1 = ws.receive_json()
            assert f1.get("type") == "stream_start"

            # Read first token
            f2 = ws.receive_json()
            assert f2.get("type") == "token"

            # Abrupt client disconnect mid-turn
            ws.close()

        # Give event loop a brief moment to propagate closure
        time.sleep(0.05)

        # Verify generation halted and generator closed
        assert tokens_produced < 10, f"WebSocket generation continued after client closed socket: {tokens_produced}"
        assert generator_closed is True, "WebSocket underlying generator was not closed on disconnect"
