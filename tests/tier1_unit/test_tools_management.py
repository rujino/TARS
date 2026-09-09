"""Unit and integration test suite for TARS Tools Management and OAuth linking (Generation 5).

Covers:
1. ToolRegistry schema export and disabled_tools filtering.
2. REST API endpoints:
   - GET /api/v1/tools/servers
   - PATCH /api/v1/tools/{tool_name}/toggle
   - GET /api/v1/tools/auth/google/url
   - GET /api/v1/tools/auth/google/callback
   - POST /api/v1/tools/auth/google/mock-link
   - POST /api/v1/tools/servers/{server_id}/test
3. Concurrency and multi-tenant isolation.
4. LangGraph agent runtime filtering (session_node, llm_node, tool_node).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import HumanMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tars.adapters.base import LLMResponse, ToolCallData
from tars.api.app import create_app
from tars.api.dependencies import (
    build_tool_registry,
    get_db_session,
    get_storage_manager,
    get_tool_registry,
)
from tars.core.security import create_access_token
from tars.db.models import TARSSettings, User
from tars.orchestrator.nodes import llm_node, session_node, tool_node
from tars.orchestrator.state import TARSState
from tars.storage.manager import FileStorageManager
from tars.tools.base import BaseTool
from tars.tools.mcp.adapter import MCPToolAdapter
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import MCPServerConfig, MCPToolMeta, MCPTransportType
from tars.tools.registry import ToolRegistry

# ============================================================================
# Test Fixtures & Helpers
# ============================================================================


class DummyTool(BaseTool):
    """Simple test tool implementation."""

    def __init__(self, name: str, description: str = "Test tool") -> None:
        super().__init__(
            name=name,
            description=description,
            parameters_schema={
                "type": "object",
                "properties": {"arg1": {"type": "string"}},
            },
        )
        self.execute_count = 0

    async def aexecute(self, **kwargs: Any) -> Any:
        self.execute_count += 1
        return {"result": f"Executed {self.name} with {kwargs}"}


@pytest.fixture
def populated_registry() -> ToolRegistry:
    """Registry with a mix of tools."""
    registry = ToolRegistry()
    registry.register(DummyTool("tool_alpha", "First test tool"))
    registry.register(DummyTool("tool_beta", "Second test tool"))
    registry.register(DummyTool("tool_gamma", "Third test tool"))
    return registry


@pytest_asyncio.fixture
async def tools_registry() -> ToolRegistry:
    """ToolRegistry singleton for tests."""
    return await build_tool_registry()


@pytest_asyncio.fixture
async def tools_api_client(
    test_engine: AsyncEngine,
    temp_storage_root: Any,
    tools_registry: ToolRegistry,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide AsyncClient wired to test_engine and default tool registry."""
    app = create_app()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_storage_manager] = lambda: FileStorageManager(
        base_dir=temp_storage_root
    )
    app.dependency_overrides[get_tool_registry] = lambda: tools_registry

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ============================================================================
# 1. ToolRegistry Declaration Filtering Tests
# ============================================================================


def test_registry_export_gemini_declarations_no_filter(
    populated_registry: ToolRegistry,
) -> None:
    """Exporting declarations without filter returns all registered tools."""
    decls = populated_registry.export_gemini_declarations()
    assert len(decls) == 3
    names = {d["name"] for d in decls}
    assert names == {"tool_alpha", "tool_beta", "tool_gamma"}


def test_registry_export_gemini_declarations_with_filter(
    populated_registry: ToolRegistry,
) -> None:
    """Exporting declarations filters out disabled tool names."""
    decls = populated_registry.export_gemini_declarations(
        disabled_tools=["tool_beta"]
    )
    assert len(decls) == 2
    names = {d["name"] for d in decls}
    assert names == {"tool_alpha", "tool_gamma"}


def test_registry_export_gemini_declarations_all_disabled(
    populated_registry: ToolRegistry,
) -> None:
    """When all tools are disabled, export returns an empty list."""
    decls = populated_registry.export_gemini_declarations(
        disabled_tools=["tool_alpha", "tool_beta", "tool_gamma"]
    )
    assert decls == []


def test_registry_export_schemas_forwards_disabled_tools(
    populated_registry: ToolRegistry,
) -> None:
    """export_schemas accepts disabled_tools and excludes them."""
    decls = populated_registry.export_schemas(disabled_tools={"tool_alpha"})
    assert len(decls) == 2
    names = {d["name"] for d in decls}
    assert "tool_alpha" not in names


def test_registry_export_openai_schemas_with_filter(
    populated_registry: ToolRegistry,
) -> None:
    """OpenAI schema export correctly respects disabled_tools."""
    schemas = populated_registry.export_openai_schemas(disabled_tools=["tool_gamma"])
    assert len(schemas) == 2
    names = {s["function"]["name"] for s in schemas}
    assert names == {"tool_alpha", "tool_beta"}


# ============================================================================
# 2. REST API: GET /api/v1/tools/servers Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_servers_unauthenticated(tools_api_client: AsyncClient) -> None:
    """Unauthenticated request to /servers returns 401 Unauthorized."""
    resp = await tools_api_client.get("/api/v1/tools/servers")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_servers_authenticated_default(
    tools_api_client: AsyncClient,
    test_user_token: str,
) -> None:
    """Authenticated user retrieves servers list with Google Workspace integration."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = await tools_api_client.get("/api/v1/tools/servers", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "servers" in data
    assert len(data["servers"]) >= 1

    # Inspect Google Workspace server
    gw = next((s for s in data["servers"] if s["id"] == "google_workspace"), None)
    assert gw is not None
    assert gw["name"] == "Google Workspace"
    assert gw["type"] == "builtin"
    assert gw["status"] in ("mock", "connected", "offline")
    assert gw["total_tools"] > 0
    assert gw["active_tools"] == gw["total_tools"]  # Default: none disabled

    tool_names = [t["name"] for t in gw["tools"]]
    assert "calendar_list_events" in tool_names
    assert "gmail_search_messages" in tool_names
    for t in gw["tools"]:
        assert t["active"] is True
        assert t["enabled"] is True


@pytest.mark.asyncio
async def test_get_servers_reflects_disabled_tools(
    tools_api_client: AsyncClient,
    test_user_token: str,
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """Disabled tools in user TARSSettings are accurately reflected in /servers."""
    # Pre-disable a tool for test_user
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    settings.disabled_tools = ["calendar_list_events"]
    await async_db_session.commit()

    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = await tools_api_client.get("/api/v1/tools/servers", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    gw = next(s for s in data["servers"] if s["id"] == "google_workspace")
    cal_tool = next(t for t in gw["tools"] if t["name"] == "calendar_list_events")
    assert cal_tool["active"] is False
    assert cal_tool["enabled"] is False
    assert gw["active_tools"] == gw["total_tools"] - 1


@pytest.mark.asyncio
async def test_get_servers_multi_user_isolation(
    tools_api_client: AsyncClient,
    test_user_token: str,
    seed_second_user: User,
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """User A disabling a tool does not affect User B's /servers tool states."""
    # User A disables gmail_send_message
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings_a = res.scalar_one()
    settings_a.disabled_tools = ["gmail_send_message"]
    await async_db_session.commit()

    token_b = create_access_token(data={"sub": seed_second_user.id})

    # Query User A
    resp_a = await tools_api_client.get(
        "/api/v1/tools/servers", headers={"Authorization": f"Bearer {test_user_token}"}
    )
    gw_a = next(s for s in resp_a.json()["servers"] if s["id"] == "google_workspace")
    gmail_a = next(t for t in gw_a["tools"] if t["name"] == "gmail_send_message")
    assert gmail_a["active"] is False

    # Query User B
    resp_b = await tools_api_client.get(
        "/api/v1/tools/servers", headers={"Authorization": f"Bearer {token_b}"}
    )
    gw_b = next(s for s in resp_b.json()["servers"] if s["id"] == "google_workspace")
    gmail_b = next(t for t in gw_b["tools"] if t["name"] == "gmail_send_message")
    assert gmail_b["active"] is True


# ============================================================================
# 3. REST API: PATCH /api/v1/tools/{tool_name}/toggle Tests
# ============================================================================


@pytest.mark.asyncio
async def test_toggle_tool_unauthenticated(tools_api_client: AsyncClient) -> None:
    """Unauthenticated toggle call returns 401."""
    resp = await tools_api_client.patch("/api/v1/tools/calendar_list_events/toggle")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_toggle_tool_not_found(
    tools_api_client: AsyncClient,
    test_user_token: str,
) -> None:
    """Toggling a non-registered tool returns 404 Not Found."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = await tools_api_client.patch(
        "/api/v1/tools/nonexistent_tool_xyz/toggle",
        headers=headers,
    )
    assert resp.status_code == 404
    assert "not found in registry" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_toggle_tool_alternating_state(
    tools_api_client: AsyncClient,
    test_user_token: str,
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """Calling toggle without body toggles enabled -> disabled -> enabled."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # 1. First toggle: tool is initially enabled -> becomes disabled
    resp1 = await tools_api_client.patch(
        "/api/v1/tools/calendar_list_events/toggle",
        headers=headers,
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["tool_name"] == "calendar_list_events"
    assert data1["active"] is False
    assert "calendar_list_events" in data1["disabled_tools"]

    # Verify DB persistence
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    await async_db_session.refresh(settings)
    assert "calendar_list_events" in settings.disabled_tools

    # 2. Second toggle: tool becomes enabled
    resp2 = await tools_api_client.patch(
        "/api/v1/tools/calendar_list_events/toggle",
        headers=headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["active"] is True
    assert "calendar_list_events" not in data2["disabled_tools"]


@pytest.mark.asyncio
async def test_toggle_tool_explicit_payload(
    tools_api_client: AsyncClient,
    test_user_token: str,
) -> None:
    """Calling toggle with explicit payload sets the requested state idempotently."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # Explicitly disable
    resp1 = await tools_api_client.patch(
        "/api/v1/tools/calendar_list_events/toggle",
        json={"active": False},
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp1.json()["active"] is False

    # Repeat explicit disable (idempotent)
    resp2 = await tools_api_client.patch(
        "/api/v1/tools/calendar_list_events/toggle",
        json={"active": False},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["active"] is False
    assert resp2.json()["disabled_tools"].count("calendar_list_events") == 1

    # Explicitly enable using enabled alias
    resp3 = await tools_api_client.patch(
        "/api/v1/tools/calendar_list_events/toggle",
        json={"enabled": True},
        headers=headers,
    )
    assert resp3.status_code == 200
    assert resp3.json()["active"] is True
    assert "calendar_list_events" not in resp3.json()["disabled_tools"]


# ============================================================================
# 4. REST API: Google OAuth2 & Mock Linking Tests
# ============================================================================


@pytest.mark.asyncio
async def test_google_auth_url_endpoint(
    tools_api_client: AsyncClient,
    test_user_token: str,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """GET /auth/google/url returns 400 if client_id missing, and valid URL when configured."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # 1. Missing client ID -> 400 Bad Request
    resp_missing = await tools_api_client.get("/api/v1/tools/auth/google/url", headers=headers)
    assert resp_missing.status_code == 400
    assert "Google OAuth2 Client ID가 설정되지 않았습니다" in resp_missing.json()["detail"]

    # 2. Configure client ID in DB
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    settings.google_client_id = "test_client_id_123.apps.googleusercontent.com"
    await async_db_session.commit()

    # 3. Successful URL generation
    resp = await tools_api_client.get("/api/v1/tools/auth/google/url", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "url" in data
    assert "accounts.google.com/o/oauth2/v2/auth" in data["url"]
    assert "client_id=test_client_id_123.apps.googleusercontent.com" in data["url"]
    assert "response_type=code" in data["url"]
    assert "state=" in data["url"]
    assert "access_type=offline" in data["url"]
    assert "scopes" in data
    assert any("calendar" in s for s in data["scopes"])
    assert any("gmail" in s for s in data["scopes"])


@pytest.mark.asyncio
async def test_google_auth_callback_error_query(
    tools_api_client: AsyncClient,
) -> None:
    """Callback with error param returns 400 Bad Request."""
    resp = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        params={"code": "123", "error": "access_denied"},
    )
    assert resp.status_code == 400
    assert "access_denied" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_google_auth_callback_missing_or_invalid_state(
    tools_api_client: AsyncClient,
) -> None:
    """Callback with missing or invalid state returns 400 Bad Request."""
    resp1 = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        params={"code": "mock_code_123"},
    )
    assert resp1.status_code == 400

    resp2 = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        params={"code": "mock_code_123", "state": "invalid.jwt.token"},
    )
    assert resp2.status_code == 400


@pytest.mark.asyncio
async def test_google_auth_callback_mock_code_success(
    tools_api_client: AsyncClient,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """Callback with valid state token and mock code successfully updates DB credentials."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )

    resp = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "application/json"},
        params={"code": "mock_auth_code_xyz", "state": state_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["linked"] is True
    assert data["is_mock"] is True
    assert data["account_email"] is not None

    # Verify DB persistence
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    await async_db_session.refresh(settings)
    assert settings.google_mock_linked is True
    assert settings.google_refresh_token is not None


@pytest.mark.asyncio
async def test_google_auth_callback_redirect_default_and_browser(
    tools_api_client: AsyncClient,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """Callback returns 302 RedirectResponse to /?auth_status=google_linked for browser and default requests."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )

    # 1. Default request flow (no Accept header specified, httpx default)
    resp_default = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        params={"code": "mock_redirect_default", "state": state_token},
        follow_redirects=False,
    )
    assert resp_default.status_code == 302
    assert resp_default.headers.get("location") == "/?auth_status=google_linked"

    # Verify DB was updated
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    await async_db_session.refresh(settings)
    assert settings.google_mock_linked is True

    # 2. Browser request flow (Accept: text/html)
    resp_browser = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        params={"code": "mock_redirect_browser", "state": state_token},
        follow_redirects=False,
    )
    assert resp_browser.status_code == 302
    assert resp_browser.headers.get("location") == "/?auth_status=google_linked"


@pytest.mark.asyncio
async def test_google_auth_callback_browser_error_redirect(
    tools_api_client: AsyncClient,
) -> None:
    """When error occurs during browser redirect flow, redirects to /?auth_status=error&error={encoded_error}."""
    # OAuth provider error
    resp = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "text/html,application/xhtml+xml"},
        params={"code": "123", "error": "access_denied"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers.get("location", "")
    assert loc.startswith("/?auth_status=error")
    assert "access_denied" in loc

    # Missing state error during browser flow
    resp_no_state = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "text/html"},
        params={"code": "mock_code"},
        follow_redirects=False,
    )
    assert resp_no_state.status_code == 302
    loc_no_state = resp_no_state.headers.get("location", "")
    assert loc_no_state.startswith("/?auth_status=error")
    assert "Invalid+or+expired" in loc_no_state


@pytest.mark.asyncio
async def test_google_auth_callback_format_json_query(
    tools_api_client: AsyncClient,
    test_user: User,
) -> None:
    """Callback with format=json query parameter returns JSON response even without Accept: application/json."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )
    resp = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        params={"code": "mock_code", "state": state_token, "format": "json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["linked"] is True


@pytest.mark.asyncio
async def test_google_auth_callback_empty_code_validation(
    tools_api_client: AsyncClient,
    test_user: User,
) -> None:
    """Empty or whitespace authorization code is rejected with 400 Bad Request."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )
    # Empty code
    resp1 = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "application/json"},
        params={"code": "", "state": state_token},
    )
    assert resp1.status_code == 400
    assert "Authorization code cannot be empty" in resp1.json()["detail"]

    # Whitespace code
    resp2 = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "application/json"},
        params={"code": "   ", "state": state_token},
    )
    assert resp2.status_code == 400
    assert "Authorization code cannot be empty" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_google_auth_callback_csrf_state_token_type_assertion(
    tools_api_client: AsyncClient,
    test_user: User,
) -> None:
    """State token without type='oauth_state' (e.g. login JWT) is rejected with 400 Bad Request."""
    # Standard login token with default type="access"
    login_token = create_access_token(
        data={"sub": test_user.id, "type": "access"},
        expires_delta=timedelta(minutes=15),
    )
    resp = await tools_api_client.get(
        "/api/v1/tools/auth/google/callback",
        headers={"Accept": "application/json"},
        params={"code": "mock_code", "state": login_token},
    )
    assert resp.status_code == 400
    assert "Invalid or expired OAuth state parameter" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_google_mock_link_toggle(
    tools_api_client: AsyncClient,
    test_user_token: str,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """POST /auth/google/mock-link toggles mock credentials on and off in DB."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # 1. Toggle ON
    resp1 = await tools_api_client.post(
        "/api/v1/tools/auth/google/mock-link",
        headers=headers,
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "success"
    assert data1["mock_linked"] is True
    assert data1["linked"] is True
    assert data1["account_email"] == "cooper@endurance.space"

    # Verify DB
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    await async_db_session.refresh(settings)
    assert settings.google_mock_linked is True
    assert settings.google_refresh_token == "mock_google_refresh_token"

    # 2. Toggle OFF
    resp2 = await tools_api_client.post(
        "/api/v1/tools/auth/google/mock-link",
        headers=headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["mock_linked"] is False
    assert data2["linked"] is False

    # Verify DB
    await async_db_session.refresh(settings)
    assert not bool(settings.google_mock_linked)
    assert settings.google_refresh_token is None


@pytest.mark.asyncio
async def test_server_test_connectivity_endpoint(
    tools_api_client: AsyncClient,
    test_user_token: str,
) -> None:
    """POST /servers/{server_id}/test returns diagnostics for Google Workspace."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = await tools_api_client.post(
        "/api/v1/tools/servers/google_workspace/test",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_id"] == "google_workspace"
    assert data["status"] in ("connected", "offline", "mock")


# ============================================================================
# 5. LangGraph Agent Runtime Filtering Tests
# ============================================================================


@pytest.mark.asyncio
async def test_session_node_hydrates_disabled_tools(
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """session_node loads disabled_tools from TARSSettings into graph state."""
    # Persist disabled tool in DB
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    settings.disabled_tools = ["calendar_delete_event"]
    await async_db_session.commit()

    initial_state: TARSState = {
        "user_id": test_user.id,
        "active_query": "Delete yesterday's meeting",
        "messages": [HumanMessage(content="Delete yesterday's meeting")],
    }

    state_update = await session_node(
        state=initial_state,
        db_session=async_db_session,
    )
    assert "disabled_tools" in state_update
    assert state_update["disabled_tools"] == ["calendar_delete_event"]


@pytest.mark.asyncio
async def test_llm_node_filters_declarations(
    populated_registry: ToolRegistry,
) -> None:
    """llm_node passes disabled_tools to tool_registry and strips them before LLM call."""
    mock_router = MagicMock()
    mock_router.route_and_generate_response = AsyncMock(
        return_value=LLMResponse(content="Understood, executing task.", tool_calls=[])
    )

    state: TARSState = {
        "messages": [HumanMessage(content="Run test tool")],
        "system_prompt": "You are TARS.",
        "disabled_tools": ["tool_beta"],
    }

    await llm_node(
        state=state,
        router=mock_router,
        tool_registry=populated_registry,
    )

    # Verify declarations passed to route_and_generate_response
    mock_router.route_and_generate_response.assert_awaited_once()
    call_kwargs = mock_router.route_and_generate_response.call_args.kwargs
    passed_tools = call_kwargs["tools"]
    tool_names = [t["name"] for t in passed_tools]
    assert "tool_beta" not in tool_names
    assert "tool_alpha" in tool_names
    assert "tool_gamma" in tool_names


@pytest.mark.asyncio
async def test_tool_node_blocks_disabled_tool(
    populated_registry: ToolRegistry,
) -> None:
    """tool_node defense-in-depth guard intercepts and blocks disabled tool calls."""
    target_tool = populated_registry.get_tool("tool_beta")
    assert isinstance(target_tool, DummyTool)

    tc = ToolCallData(id="call_test_1", name="tool_beta", arguments={"arg1": "val"})

    state: TARSState = {
        "tool_calls": [tc],
        "disabled_tools": ["tool_beta"],
        "iteration_count": 0,
        "tool_results": [],
    }

    state_update = await tool_node(state=state, tool_registry=populated_registry)

    # 1. Target tool was NEVER executed
    assert target_tool.execute_count == 0

    # 2. ToolMessage delimiter emitted
    messages = state_update["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    content_str = str(messages[0].content)
    assert "[Tool Blocked: tool_beta]" in content_str
    assert "disabled" in content_str.lower()

    # 3. Error recorded in tool_results
    results = state_update["tool_results"]
    assert len(results) == 1
    assert results[0]["tool"] == "tool_beta"
    assert results[0]["status"] == "error"
    assert "disabled" in results[0]["error"].lower()


@pytest.mark.asyncio
async def test_tool_node_executes_enabled_tool(
    populated_registry: ToolRegistry,
) -> None:
    """tool_node executes enabled tool normally when not disabled."""
    target_tool = populated_registry.get_tool("tool_alpha")
    assert isinstance(target_tool, DummyTool)

    tc = ToolCallData(id="call_test_2", name="tool_alpha", arguments={"arg1": "hello"})

    state: TARSState = {
        "tool_calls": [tc],
        "disabled_tools": ["tool_beta"],  # tool_alpha is NOT disabled
        "iteration_count": 0,
        "tool_results": [],
    }

    state_update = await tool_node(state=state, tool_registry=populated_registry)

    # Target tool was executed
    assert target_tool.execute_count == 1
    assert len(state_update["messages"]) == 1
    assert "[Tool Result: tool_alpha]" in state_update["messages"][0].content
    assert state_update["tool_results"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_tool_node_mixed_enabled_and_disabled_calls(
    populated_registry: ToolRegistry,
) -> None:
    """tool_node handles mixed batch of calls: blocks disabled tool, executes enabled tool."""
    tool_alpha = populated_registry.get_tool("tool_alpha")
    tool_beta = populated_registry.get_tool("tool_beta")
    assert isinstance(tool_alpha, DummyTool)
    assert isinstance(tool_beta, DummyTool)

    tc1 = ToolCallData(id="call_alpha", name="tool_alpha", arguments={"arg1": "run"})
    tc2 = ToolCallData(id="call_beta", name="tool_beta", arguments={"arg1": "block"})

    state: TARSState = {
        "tool_calls": [tc1, tc2],
        "disabled_tools": ["tool_beta"],
        "iteration_count": 0,
        "tool_results": [],
    }

    state_update = await tool_node(state=state, tool_registry=populated_registry)

    # tool_alpha executed, tool_beta blocked
    assert tool_alpha.execute_count == 1
    assert tool_beta.execute_count == 0

    assert len(state_update["messages"]) == 2
    assert "[Tool Result: tool_alpha]" in state_update["messages"][0].content
    assert "[Tool Blocked: tool_beta]" in state_update["messages"][1].content

    results = state_update["tool_results"]
    assert len(results) == 2
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "error"


@pytest.mark.asyncio
async def test_google_auth_callback_live_token_exchange(
    tools_api_client: AsyncClient,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """Live OAuth token exchange mock: httpx receives code and saves real access/refresh tokens in DB."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "ya29.real_live_access_token_abc",
        "refresh_token": "1//real_live_refresh_token_xyz",
        "email": "pilot@endurance.space",
    }

    mock_settings = MagicMock()
    mock_settings.google_mock_mode = False
    mock_settings.google_client_id = "mock_client_id"
    mock_settings.google_client_secret = "mock_client_secret"

    with patch("tars.api.routers.tools.get_settings", return_value=mock_settings), patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ) as mock_post:
        resp = await tools_api_client.get(
            "/api/v1/tools/auth/google/callback",
            headers={"Accept": "application/json"},
            params={"code": "4/real_auth_code_123", "state": state_token},
        )
        assert resp.status_code == 200
        mock_post.assert_awaited_once()
        data = resp.json()
        assert data["linked"] is True
        assert data["is_mock"] is False
        assert data["account_email"] == "pilot@endurance.space"

        # Verify DB
        stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
        res = await async_db_session.execute(stmt)
        settings = res.scalar_one()
        await async_db_session.refresh(settings)
        assert settings.google_mock_linked is False
        assert settings.google_refresh_token == "1//real_live_refresh_token_xyz"
        assert settings.google_access_token == "ya29.real_live_access_token_abc"
        assert settings.google_linked_email == "pilot@endurance.space"


@pytest.mark.asyncio
async def test_google_auth_callback_token_endpoint_failure(
    tools_api_client: AsyncClient,
    test_user: User,
) -> None:
    """When Google token endpoint returns 400 invalid_grant, callback raises 400 Bad Request."""
    state_token = create_access_token(
        data={"sub": test_user.id, "type": "oauth_state"},
        expires_delta=timedelta(minutes=5),
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid_grant: code expired"

    mock_settings = MagicMock()
    mock_settings.google_mock_mode = False
    mock_settings.google_client_id = "mock_client_id"
    mock_settings.google_client_secret = "mock_client_secret"

    with patch("tars.api.routers.tools.get_settings", return_value=mock_settings), patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ):
        resp = await tools_api_client.get(
            "/api/v1/tools/auth/google/callback",
            params={"code": "expired_code", "state": state_token},
        )
        assert resp.status_code == 400
        assert "Token exchange failed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_servers_with_mcp_server(
    tools_api_client: AsyncClient,
    test_user_token: str,
    tools_registry: ToolRegistry,
) -> None:
    """GET /servers correctly discovers and returns configured MCP servers and their tools."""
    mcp_config = MCPServerConfig(
        name="weather_station",
        transport=MCPTransportType.MOCK,
    )
    mcp_client = AsyncMCPClient(config=mcp_config)
    mcp_client.register_mock_tool(
        MCPToolMeta(
            name="get_temperature",
            description="Returns current temperature",
            inputSchema={"type": "object", "properties": {"location": {"type": "string"}}},
        )
    )
    mcp_adapter = MCPToolAdapter(client=mcp_client, meta=MCPToolMeta(
        name="get_temperature",
        description="Returns current temperature",
        inputSchema={"type": "object", "properties": {"location": {"type": "string"}}},
    ))
    tools_registry.register(mcp_adapter)
    tools_registry.track_client(mcp_client)

    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = await tools_api_client.get("/api/v1/tools/servers", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    mcp_srv = next((s for s in data["servers"] if s["id"] == "weather_station"), None)
    assert mcp_srv is not None
    assert mcp_srv["type"] == "mcp"
    assert mcp_srv["status"] == "mock"
    assert mcp_srv["total_tools"] == 1
    assert mcp_srv["active_tools"] == 1
    assert mcp_srv["tools"][0]["name"] == "get_temperature"

    # Also test connectivity test endpoint on this MCP server
    test_resp = await tools_api_client.post(
        "/api/v1/tools/servers/weather_station/test",
        headers=headers,
    )
    assert test_resp.status_code == 200
    assert test_resp.json()["status"] == "mock"

    # Test nonexistent server test returns 404
    err_resp = await tools_api_client.post(
        "/api/v1/tools/servers/nonexistent_srv_404/test",
        headers=headers,
    )
    assert err_resp.status_code == 404


def test_tars_settings_model_properties() -> None:
    """Test TARSSettings compatibility properties and setters."""
    settings = TARSSettings(user_id="test_prop_user")
    assert not bool(settings.google_linked)
    assert not bool(settings.google_is_mock)
    assert settings.google_account_email is None

    # Link via property
    settings.google_mock_linked = True
    assert bool(settings.google_linked)
    assert bool(settings.google_is_mock)

    # Account email
    settings.google_account_email = "test@endurance.space"
    assert settings.google_linked_email == "test@endurance.space"

    # Unlink via property
    settings.google_linked = False
    assert not bool(settings.google_mock_linked)
    assert settings.google_linked_email is None


@pytest.mark.asyncio
async def test_google_credentials_get_and_post_endpoints(
    tools_api_client: AsyncClient,
    test_user_token: str,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """GET /auth/google/credentials and POST /auth/google/credentials update settings."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # 1. Initial state
    resp = await tools_api_client.get("/api/v1/tools/auth/google/credentials", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "client_id" in data
    assert "has_client_secret" in data
    assert "is_configured" in data

    # 2. Update credentials
    update_payload = {
        "client_id": "test_client_id_123.apps.googleusercontent.com",
        "client_secret": "GOCSPX-test_secret_abc",
    }
    resp_post = await tools_api_client.post(
        "/api/v1/tools/auth/google/credentials",
        headers=headers,
        json=update_payload,
    )
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post["client_id"] == "test_client_id_123.apps.googleusercontent.com"
    assert data_post["has_client_secret"] is True
    assert data_post["is_configured"] is True

    # 3. Verify in DB
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    await async_db_session.refresh(settings)
    assert settings.google_client_id == "test_client_id_123.apps.googleusercontent.com"
    assert settings.google_client_secret == "GOCSPX-test_secret_abc"


@pytest.mark.asyncio
async def test_google_disconnect_endpoint(
    tools_api_client: AsyncClient,
    test_user_token: str,
    test_user: User,
    async_db_session: AsyncSession,
) -> None:
    """POST /auth/google/disconnect clears tokens and unlinks Google account."""
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # Seed linked settings
    stmt = select(TARSSettings).where(TARSSettings.user_id == test_user.id)
    res = await async_db_session.execute(stmt)
    settings = res.scalar_one()
    settings.google_refresh_token = "refresh_to_disconnect"
    settings.google_access_token = "access_to_disconnect"
    settings.google_linked_email = "connected_user@nyoru.kr"
    await async_db_session.commit()

    # Disconnect
    resp = await tools_api_client.post("/api/v1/tools/auth/google/disconnect", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["linked"] is False

    # Verify cleared in DB
    await async_db_session.refresh(settings)
    assert settings.google_refresh_token is None
    assert settings.google_access_token is None
    assert settings.google_linked_email is None
    assert bool(settings.google_linked) is False


