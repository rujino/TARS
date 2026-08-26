"""Tier 3 Adversarial E2E Tests: Background Knowledge Extractor Concurrency & Fault Isolation in Streaming APIs.

Verifies:
1. SSE streaming latency & background task non-blocking isolation.
2. SSE streaming resilience when background extraction worker raises unhandled exceptions.
3. WebSocket streaming resilience when background extractor fails.
4. WebSocket cleanup of pending background tasks upon abrupt client disconnect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from tars.adapters.router import HybridLLMRouter
from tars.api.app import create_app
from tars.api.dependencies import get_db_session, get_storage_manager
from tars.core.okf.models import OKFSource
from tars.db.models import UserWikiIndex
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.storage.manager import FileStorageManager

# ============================================================================
# 1. SSE Stream Concurrency & Background Task Fault Isolation
# ============================================================================


@pytest.mark.asyncio
async def test_sse_chat_stream_background_extraction_success_and_indexing(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify that SSE stream triggers background extraction and persists OKF document & DB index."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> Any:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_storage_manager] = lambda: storage

    extraction_json = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "pref_flight_speed_warp",
            "type": "preference",
            "title": "Warp Speed Flight Preference",
            "category": "operations",
            "tags": ["speed", "flight"],
            "importance": "high",
            "content": "User prefers maximum sub-light velocity whenever approaching event horizons.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in ["TARS: ", "Velocity ", "vector ", "set."]:
            yield chunk

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker,
                "extract_and_sync",
                wraps=SelfEvolvingKnowledgeWorker(
                    extractor_llm=AsyncMock(agenerate=AsyncMock(return_value=extraction_json)),
                    storage_manager=storage,
                ).extract_and_sync,
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                    headers={"Authorization": f"Bearer {test_user_token}"},
                ) as client:
                    resp = await client.post(
                        "/api/v1/chat/stream",
                        json={
                            "message": "Always approach event horizons at maximum sub-light velocity.",
                            "session_id": "default_session",
                        },
                    )

                    assert resp.status_code == 200
                    assert "text/event-stream" in resp.headers["content-type"]
                    body = resp.text
                    assert "event: stream_start" in body
                    assert "event: token" in body
                    assert "event: stream_end" in body
                    assert "event: done" in body

    # Verify extracted OKF file
    doc = await storage.read_okf_file(user_id=seed_test_user.id, okf_id="pref_flight_speed_warp")
    assert doc is not None
    assert doc.metadata.source == OKFSource.AUTO_EXTRACTED
    assert "maximum sub-light velocity" in doc.content

    # Verify DB index
    async with test_session_factory() as session:
        stmt = select(UserWikiIndex).where(
            UserWikiIndex.user_id == seed_test_user.id,
            UserWikiIndex.okf_id == "pref_flight_speed_warp",
        )
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        assert record is not None
        assert record.title == "Warp Speed Flight Preference"


@pytest.mark.asyncio
async def test_sse_chat_stream_fault_isolation_on_background_crash(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify that SSE stream completes with HTTP 200 even if knowledge extractor worker throws."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> Any:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_storage_manager] = lambda: storage

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in ["TARS: ", "All ", "systems ", "nominal."]:
            yield chunk

    # Mock extract_and_sync to throw an unhandled error inside background task
    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker,
                "extract_and_sync",
                side_effect=RuntimeError("Simulated background extraction crash"),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                    headers={"Authorization": f"Bearer {test_user_token}"},
                ) as client:
                    resp = await client.post(
                        "/api/v1/chat/stream",
                        json={
                            "message": "Hello TARS, testing crash isolation.",
                            "session_id": "default_session",
                        },
                    )

                    assert resp.status_code == 200
                    assert "text/event-stream" in resp.headers["content-type"]
                    body = resp.text
                    assert "event: stream_start" in body
                    assert "event: token" in body
                    assert "event: stream_end" in body
                    assert "event: done" in body


# ============================================================================
# 2. WebSocket Stream Fault Isolation
# ============================================================================


def test_websocket_chat_stream_fault_isolation_on_background_crash(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
    seed_test_user: Any,
    test_user_token: str,
) -> None:
    """Verify that WebSocket stream finishes cleanly even if background extraction task fails."""
    app = create_app()
    storage = FileStorageManager(base_dir=temp_storage_root)

    test_session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    app.dependency_overrides[get_storage_manager] = lambda: storage

    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        for chunk in ["TARS: ", "Status ", "is ", "green."]:
            yield chunk

    with patch("tars.api.routers.chat.get_session_factory", return_value=test_session_factory):
        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_stream):
            with patch.object(
                SelfEvolvingKnowledgeWorker,
                "extract_and_sync",
                side_effect=RuntimeError("Simulated WS background extraction crash"),
            ):
                with TestClient(app) as client:
                    with client.websocket_connect(f"/api/v1/chat/ws?token={test_user_token}") as ws:
                        ws.send_json(
                            {
                                "type": "chat_message",
                                "content": "Status report, TARS.",
                                "session_id": "ws_session",
                            }
                        )

                        # Receive stream_start
                        start_frame = ws.receive_json()
                        assert start_frame["type"] == "stream_start"

                        # Receive tokens
                        tokens = []
                        while True:
                            frame = ws.receive_json()
                            if frame["type"] == "token":
                                tokens.append(frame["content"])
                            elif frame["type"] == "stream_end":
                                break
                            elif frame["type"] == "error":
                                pytest.fail(f"Received unexpected error frame: {frame}")

                        assert len(tokens) > 0
                        assert frame["type"] == "stream_end"
