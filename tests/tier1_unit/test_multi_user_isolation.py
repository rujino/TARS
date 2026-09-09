"""Tests for multi-tenant request isolation, Google OAuth per-user scoping, and token encryption at rest."""

from __future__ import annotations

import asyncio
from typing import Any
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tars.core.security import decrypt_secret, encrypt_secret
from tars.db.base import Base
from tars.db.models import TARSSettings, User
from tars.orchestrator.nodes import tool_node
from tars.orchestrator.state import TARSState
from tars.tools.base import BaseTool
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import GoogleCalendarAdapter
from tars.tools.google.gmail import GmailAdapter
from tars.tools.registry import ToolRegistry


@pytest.fixture
async def multi_user_db():
    """In-memory SQLite database with User and TARSSettings tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed User A (connected) and User B (unconnected)
    async with session_maker() as session:
        user_a = User(id="user_a_id", username="user_a", email="user_a@test.com", hashed_password="dummy_hash")
        user_b = User(id="user_b_id", username="user_b", email="user_b@test.com", hashed_password="dummy_hash")
        session.add_all([user_a, user_b])
        await session.commit()

        # User A has valid mock linked settings
        settings_a = TARSSettings(
            user_id=user_a.id,
            google_refresh_token="refresh_token_user_a",
            google_access_token="access_token_user_a",
            google_mock_linked=True,
            google_linked_email="user_a@gmail.com",
            google_client_id="client_id_a",
            google_client_secret="client_secret_a",
        )
        # User B has no google credentials linked
        settings_b = TARSSettings(
            user_id=user_b.id,
            google_refresh_token=None,
            google_access_token=None,
            google_mock_linked=False,
            google_linked_email=None,
        )
        session.add_all([settings_a, settings_b])
        await session.commit()

    yield session_maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_token_encryption_at_rest_and_backward_compatibility(multi_user_db):
    """Verify that sensitive OAuth tokens are encrypted with 'enc:' prefix in DB and decrypted on read."""
    session_maker = multi_user_db

    # 1. Verify that User A's token was encrypted on insert
    async with session_maker() as session:
        result = await session.execute(
            text("SELECT google_refresh_token, google_access_token, google_client_secret FROM tars_settings WHERE user_id = 'user_a_id'")
        )
        row = result.fetchone()
        raw_refresh, raw_access, raw_secret = row[0], row[1], row[2]

        assert raw_refresh.startswith("enc:")
        assert "refresh_token_user_a" not in raw_refresh
        assert raw_access.startswith("enc:")
        assert "access_token_user_a" not in raw_access
        assert raw_secret.startswith("enc:")
        assert "client_secret_a" not in raw_secret

    # 2. Verify that reading via ORM returns the decrypted plaintext
    async with session_maker() as session:
        stmt = select(TARSSettings).where(TARSSettings.user_id == "user_a_id")
        settings = (await session.execute(stmt)).scalar_one()

        assert settings.google_refresh_token == "refresh_token_user_a"
        assert settings.google_access_token == "access_token_user_a"
        assert settings.google_client_secret == "client_secret_a"

    # 3. Test backward compatibility: manually insert a plaintext legacy token
    async with session_maker() as session:
        await session.execute(
            text("UPDATE tars_settings SET google_refresh_token = 'legacy_plaintext_tok' WHERE user_id = 'user_b_id'")
        )
        await session.commit()

    async with session_maker() as session:
        stmt = select(TARSSettings).where(TARSSettings.user_id == "user_b_id")
        settings_b = (await session.execute(stmt)).scalar_one()
        # Should transparently return plaintext without error
        assert settings_b.google_refresh_token == "legacy_plaintext_tok"


@pytest.mark.asyncio
async def test_multi_tenant_google_auth_scoping(monkeypatch, multi_user_db):
    """Verify GoogleAuthHelper strictly enforces user_id scoping and does not leak User A's token to User B."""
    session_maker = multi_user_db
    monkeypatch.setattr("tars.db.session.get_session_factory", lambda: session_maker)

    helper = GoogleAuthHelper(mock_mode=False)

    # User A is mock linked, should return access token
    tok_a = await helper.get_access_token(user_id="user_a_id")
    assert tok_a == "mock_google_oauth2_access_token"

    # User B has no linked credentials, should raise RuntimeError and NOT fallback to User A
    with pytest.raises(RuntimeError) as exc_info:
        await helper.get_access_token(user_id="user_b_id")
    assert "Google Workspace 계정이 연동되지 않았습니다" in str(exc_info.value)


@pytest.mark.asyncio
async def test_concurrent_tool_execution_isolation(monkeypatch, multi_user_db):
    """Verify concurrent execution from two different users is isolated and does not race."""
    session_maker = multi_user_db
    monkeypatch.setattr("tars.db.session.get_session_factory", lambda: session_maker)

    helper = GoogleAuthHelper(mock_mode=False)
    adapter = GoogleCalendarAdapter(auth_helper=helper)
    registry = ToolRegistry(adapter.get_tools())

    # User A should succeed
    res_a = await registry.execute_tool("calendar_list_events", {}, user_id="user_a_id")
    assert isinstance(res_a, list)

    # User B should fail because User B is not linked
    with pytest.raises(RuntimeError):
        await registry.execute_tool("calendar_list_events", {}, user_id="user_b_id")

    # Concurrent execution via asyncio.gather
    async def call_for_user(u_id: str):
        try:
            return await registry.execute_tool("calendar_list_events", {}, user_id=u_id)
        except Exception as e:
            return f"error: {e}"

    results = await asyncio.gather(
        call_for_user("user_a_id"),
        call_for_user("user_b_id"),
        call_for_user("user_a_id"),
    )

    assert isinstance(results[0], list)
    assert "error:" in results[1]
    assert "Google Workspace 계정이 연동되지 않았습니다" in results[1]
    assert isinstance(results[2], list)


@pytest.mark.asyncio
async def test_tool_node_passes_user_id_from_langgraph_state(monkeypatch, multi_user_db):
    """Verify tool_node extracts user_id from state and enforces isolation."""
    session_maker = multi_user_db
    monkeypatch.setattr("tars.db.session.get_session_factory", lambda: session_maker)

    helper = GoogleAuthHelper(mock_mode=False)
    adapter = GoogleCalendarAdapter(auth_helper=helper)
    registry = ToolRegistry(adapter.get_tools())

    class FakeToolCall:
        def __init__(self, name: str, args: dict[str, Any], call_id: str):
            self.name = name
            self.arguments = args
            self.id = call_id

    # 1. State for User A (connected)
    state_a: TARSState = {
        "user_id": "user_a_id",
        "session_id": "sess_a",
        "active_query": "List events",
        "tool_calls": [FakeToolCall("calendar_list_events", {}, "call_1")],
    }
    result_a = await tool_node(state=state_a, tool_registry=registry)
    tool_results_a = result_a.get("tool_results", [])
    assert len(tool_results_a) == 1
    assert tool_results_a[0]["status"] == "success"

    # 2. State for User B (unconnected)
    state_b: TARSState = {
        "user_id": "user_b_id",
        "session_id": "sess_b",
        "active_query": "List events",
        "tool_calls": [FakeToolCall("calendar_list_events", {}, "call_2")],
    }
    result_b = await tool_node(state=state_b, tool_registry=registry)
    tool_results_b = result_b.get("tool_results", [])
    assert len(tool_results_b) == 1
    assert tool_results_b[0]["status"] == "error"
    assert "Google Workspace 계정이 연동되지 않았습니다" in tool_results_b[0]["error"]


@pytest.mark.asyncio
async def test_cache_invalidation_per_user():
    """Verify invalidating a single user's cache does not evict another user's cache."""
    helper = GoogleAuthHelper(mock_mode=False)
    # Manually populate caches
    helper._user_token_cache["user_1"] = ("token_1", 9999999999.0)
    helper._user_token_cache["user_2"] = ("token_2", 9999999999.0)

    helper.invalidate_user_cache("user_1")
    assert "user_1" not in helper._user_token_cache
    assert "user_2" in helper._user_token_cache
    assert helper._user_token_cache["user_2"][0] == "token_2"


@pytest.mark.asyncio
async def test_concurrent_token_refresh_single_execution(monkeypatch, multi_user_db):
    """Verify that multiple concurrent calls for the same user only trigger ONE token refresh request (no thundering herd)."""
    session_maker = multi_user_db
    monkeypatch.setattr("tars.db.session.get_session_factory", lambda: session_maker)

    # Seed User C with active refresh token and credentials
    async with session_maker() as session:
        user_c = User(id="user_c_id", username="user_c", email="user_c@test.com", hashed_password="dummy_hash")
        session.add(user_c)
        await session.commit()

        settings_c = TARSSettings(
            user_id=user_c.id,
            google_refresh_token="refresh_token_c",
            google_access_token=None,
            google_mock_linked=False,
            google_client_id="client_id_c",
            google_client_secret="client_secret_c",
        )
        session.add(settings_c)
        await session.commit()

    network_call_count = 0

    class MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "newly_refreshed_access_token_c", "expires_in": 3600}

    class MockHttpClient:
        async def post(self, url, data=None, **kwargs):
            nonlocal network_call_count
            network_call_count += 1
            # Simulate real network roundtrip latency
            await asyncio.sleep(0.05)
            return MockResponse()

        async def aclose(self):
            pass

    helper = GoogleAuthHelper(mock_mode=False, http_client=MockHttpClient())

    # Launch 10 concurrent requests for User C
    tokens = await asyncio.gather(
        *[helper.get_access_token(user_id="user_c_id") for _ in range(10)]
    )

    # All 10 requests should receive the exact same refreshed access token
    assert len(tokens) == 10
    assert all(t == "newly_refreshed_access_token_c" for t in tokens)

    # Thanks to per-user lock and double-checked locking, network call happened strictly ONCE
    assert network_call_count == 1


@pytest.mark.asyncio
async def test_endpoint_cache_invalidation_on_credential_update_and_mock(monkeypatch, multi_user_db):
    """Verify that updating credentials and toggling mock link evicts cached tokens via tool_registry."""
    from unittest.mock import MagicMock
    from tars.api.routers.tools import GoogleCredentialsRequest, mock_link_google, update_google_credentials

    session_maker = multi_user_db
    async with session_maker() as session:
        user = (await session.execute(select(User).where(User.id == "user_a_id"))).scalar_one()

        mock_registry = MagicMock(spec=ToolRegistry)

        # 1. Update credentials should trigger invalidate_user_google_cache
        req = GoogleCredentialsRequest(client_id="new_id", client_secret="new_secret")
        await update_google_credentials(
            payload=req,
            current_user=user,
            db=session,
            tool_registry=mock_registry,
        )
        mock_registry.invalidate_user_google_cache.assert_called_with("user_a_id")

        mock_registry.reset_mock()

        # 2. Mock link toggle should also trigger invalidate_user_google_cache
        await mock_link_google(
            current_user=user,
            db=session,
            tool_registry=mock_registry,
        )
        mock_registry.invalidate_user_google_cache.assert_called_with("user_a_id")

