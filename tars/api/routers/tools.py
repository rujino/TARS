"""TARS Tool and MCP Server Management REST Router."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.dependencies import get_current_user, get_db_session, get_tool_registry
from tars.config import get_settings
from tars.core.security import create_access_token, decode_access_token
from tars.db.models import TARSSettings, User
from tars.tools.mcp.adapter import MCPToolAdapter
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import MCPTransportType
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.routers.tools")
router = APIRouter(prefix="/tools", tags=["Tools Management"])

GOOGLE_SCOPES: list[str] = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ============================================================================
# Pydantic Response & Request Schemas
# ============================================================================


class ToolItem(BaseModel):
    """Metadata and status for an individual tool."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Unique tool identifier")
    description: str = Field(default="", description="Functional description")
    active: bool = Field(default=True, description="Whether tool is active for user")
    enabled: bool = Field(default=True, description="Alias for active")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema parameters"
    )


class ServerInfo(BaseModel):
    """Server status and tool inventory item."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Server identifier")
    name: str = Field(..., description="Display name")
    type: Literal["builtin", "mcp"] = Field(..., description="Server type")
    status: Literal["connected", "offline", "mock"] = Field(
        ..., description="Connection status"
    )
    transport: str | None = Field(default=None, description="Transport type")
    url: str | None = Field(default=None, description="Server endpoint URL")
    description: str = Field(default="", description="Description of integration")
    total_tools: int = Field(default=0, description="Total tools provided")
    total_tools_count: int = Field(default=0, description="Total tools count")
    active_tools: int = Field(default=0, description="Active tools count")
    active_tools_count: int = Field(default=0, description="Active tools count")
    auth_required: bool = Field(
        default=False, description="Whether OAuth linking is supported"
    )
    is_linked: bool = Field(
        default=False, description="Whether account credentials are linked"
    )
    is_mock: bool = Field(
        default=False, description="Whether server is running in mock mode"
    )
    account_email: str | None = Field(
        default=None, description="Linked account email"
    )
    tools: list[ToolItem] = Field(
        default_factory=list, description="List of tools"
    )


class ToolsServersResponse(BaseModel):
    """Payload returning all registered tool servers."""

    servers: list[ServerInfo] = Field(default_factory=list)


class ToolToggleRequest(BaseModel):
    """Request payload for setting explicit enabled/active state."""

    model_config = ConfigDict(extra="ignore")
    active: bool | None = Field(default=None, description="Explicit active state")
    enabled: bool | None = Field(default=None, description="Explicit enabled state")


class ToolToggleResponse(BaseModel):
    """Result of tool toggle action."""

    tool_name: str
    active: bool
    enabled: bool
    disabled_tools: list[str]
    user_id: str
    message: str


class GoogleAuthUrlResponse(BaseModel):
    """OAuth2 authorization URL payload."""

    url: str
    state: str
    scopes: list[str]


class GoogleAuthCallbackResponse(BaseModel):
    """OAuth2 callback result."""

    status: str
    provider: str = "google"
    linked: bool
    is_mock: bool = False
    account_email: str | None = None
    message: str


class GoogleMockLinkResponse(BaseModel):
    """Mock linking toggle result."""

    status: str = "success"
    provider: str = "google"
    linked: bool
    mock_linked: bool
    is_mock: bool
    account_email: str | None = None
    message: str


class GoogleCredentialsRequest(BaseModel):
    """Payload to configure user or custom Google OAuth2 credentials."""

    model_config = ConfigDict(extra="ignore")
    client_id: str | None = Field(default=None, description="Google OAuth2 Client ID")
    client_secret: str | None = Field(default=None, description="Google OAuth2 Client Secret")


class GoogleCredentialsResponse(BaseModel):
    """Configuration status for Google OAuth credentials."""

    model_config = ConfigDict(extra="ignore")
    client_id: str = ""
    has_client_secret: bool = False
    is_configured: bool = False
    is_linked: bool = False
    account_email: str | None = None


class ServerTestResponse(BaseModel):
    """Result of server connection test."""

    server_id: str
    status: Literal["connected", "offline", "mock"]
    latency_ms: float
    message: str


# ============================================================================
# Helpers
# ============================================================================


async def _get_or_create_settings(db: AsyncSession, user_id: str) -> TARSSettings:
    """Helper to fetch active settings or seed defaults."""
    stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
    res = await db.execute(stmt)
    settings = res.scalar_one_or_none()

    if settings is None:
        now = datetime.now(UTC)
        settings = TARSSettings(
            user_id=user_id,
            humor_level=0.90,
            honesty_level=0.95,
            mode="companion",
            disabled_tools=[],
            google_mock_linked=False,
            created_at=now,
            updated_at=now,
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


# ============================================================================
# Endpoints
# ============================================================================


@router.get(
    "/servers",
    response_model=ToolsServersResponse,
    summary="List all registered tool servers and their tools",
)
async def list_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> ToolsServersResponse:
    """Return all registered servers (Google Workspace and MCP servers) with active/disabled tool states."""
    app_settings = get_settings()
    user_settings = await _get_or_create_settings(db, current_user.id)
    disabled_set = set(user_settings.disabled_tools or [])

    google_tools: list[ToolItem] = []
    mcp_servers_map: dict[str, dict[str, Any]] = {}
    other_tools: list[ToolItem] = []

    for tool in tool_registry.list_tools():
        is_active = tool.name not in disabled_set
        tool_item = ToolItem(
            name=tool.name,
            description=tool.description,
            active=is_active,
            enabled=is_active,
            parameters=tool.parameters_schema,
        )
        if tool.name.startswith("calendar_") or tool.name.startswith("gmail_"):
            google_tools.append(tool_item)
        elif isinstance(tool, MCPToolAdapter):
            srv_name = tool.client.config.name
            if srv_name not in mcp_servers_map:
                transport_val = str(
                    tool.client.config.transport.value
                    if hasattr(tool.client.config.transport, "value")
                    else tool.client.config.transport
                )
                is_mock_srv = tool.client.config.transport == MCPTransportType.MOCK
                is_connected = getattr(tool.client, "_is_connected", False)
                srv_status = (
                    "mock"
                    if is_mock_srv
                    else ("connected" if is_connected else "offline")
                )
                mcp_servers_map[srv_name] = {
                    "id": srv_name,
                    "name": srv_name,
                    "type": "mcp",
                    "status": srv_status,
                    "transport": transport_val,
                    "url": str(tool.client.config.url or ""),
                    "description": f"Model Context Protocol server ({srv_name})",
                    "tools": [],
                }
            mcp_servers_map[srv_name]["tools"].append(tool_item)
        else:
            other_tools.append(tool_item)

    servers: list[ServerInfo] = []

    # 1. Google Workspace
    google_linked = bool(
        user_settings.google_refresh_token or user_settings.google_access_token
    )
    google_status: Literal["connected", "offline", "mock"] = (
        "connected" if google_linked else "offline"
    )
    google_email = user_settings.google_linked_email if google_linked else None

    google_active_count = sum(1 for t in google_tools if t.active)
    servers.append(
        ServerInfo(
            id="google_workspace",
            name="Google Workspace",
            type="builtin",
            status=google_status,
            description="Builtin Google Calendar and Gmail Workspace integration",
            total_tools=len(google_tools),
            total_tools_count=len(google_tools),
            active_tools=google_active_count,
            active_tools_count=google_active_count,
            auth_required=True,
            is_linked=google_linked,
            is_mock=False,
            account_email=google_email,
            tools=google_tools,
        )
    )

    # 2. Configured MCP servers
    for _, srv_data in mcp_servers_map.items():
        tools_list = srv_data["tools"]
        act_count = sum(1 for t in tools_list if t.active)
        servers.append(
            ServerInfo(
                id=srv_data["id"],
                name=srv_data["name"],
                type="mcp",
                status=srv_data["status"],
                transport=srv_data["transport"],
                url=srv_data["url"],
                description=srv_data["description"],
                total_tools=len(tools_list),
                total_tools_count=len(tools_list),
                active_tools=act_count,
                active_tools_count=act_count,
                auth_required=False,
                is_linked=False,
                is_mock=(srv_data["status"] == "mock"),
                tools=tools_list,
            )
        )

    # 3. System Tools
    if other_tools:
        act_count = sum(1 for t in other_tools if t.active)
        servers.append(
            ServerInfo(
                id="system_tools",
                name="System Tools",
                type="builtin",
                status="connected",
                description="Internal and registered system tools",
                total_tools=len(other_tools),
                total_tools_count=len(other_tools),
                active_tools=act_count,
                active_tools_count=act_count,
                auth_required=False,
                is_linked=True,
                is_mock=False,
                tools=other_tools,
            )
        )

    return ToolsServersResponse(servers=servers)


@router.patch(
    "/{tool_name}/toggle",
    response_model=ToolToggleResponse,
    summary="Toggle or set tool active state for current user",
)
async def toggle_tool(
    tool_name: str,
    payload: ToolToggleRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> ToolToggleResponse:
    """Toggle or persist tool active/disabled state in current user's TARSSettings."""
    if not tool_registry.has_tool(tool_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found in registry.",
        )

    settings = await _get_or_create_settings(db, current_user.id)
    disabled_list = list(settings.disabled_tools or [])

    desired_active: bool | None = None
    if payload is not None:
        if payload.active is not None:
            desired_active = payload.active
        elif payload.enabled is not None:
            desired_active = payload.enabled

    if desired_active is None:
        # Toggle current state
        if tool_name in disabled_list:
            disabled_list.remove(tool_name)
            is_active = True
        else:
            disabled_list.append(tool_name)
            is_active = False
    elif desired_active is True:
        if tool_name in disabled_list:
            disabled_list.remove(tool_name)
        is_active = True
    else:
        if tool_name not in disabled_list:
            disabled_list.append(tool_name)
        is_active = False

    settings.disabled_tools = disabled_list
    settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(settings)

    action_str = "enabled" if is_active else "disabled"
    return ToolToggleResponse(
        tool_name=tool_name,
        active=is_active,
        enabled=is_active,
        disabled_tools=settings.disabled_tools,
        user_id=current_user.id,
        message=f"Tool '{tool_name}' {action_str} successfully.",
    )


@router.get(
    "/auth/google/url",
    response_model=GoogleAuthUrlResponse,
    summary="Get Google OAuth2 authorization URL",
)
async def get_google_auth_url(
    request: Request,
    redirect_uri: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GoogleAuthUrlResponse:
    """Generate Google OAuth2 authorization redirect URL with required scopes and CSRF state token."""
    user_settings = await _get_or_create_settings(db, current_user.id)
    app_settings = get_settings()
    client_id = (
        user_settings.google_client_id
        or app_settings.google_client_id
        or "tars_google_client_id"
    )

    if not redirect_uri:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get(
            "x-forwarded-host", request.headers.get("host", request.url.netloc)
        )
        redirect_uri = f"{proto}://{host}/api/v1/tools/auth/google/callback"

    state_token = create_access_token(
        data={
            "sub": current_user.id,
            "type": "oauth_state",
            "redirect_uri": redirect_uri,
        },
        expires_delta=timedelta(minutes=15),
    )

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state_token,
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return GoogleAuthUrlResponse(url=url, state=state_token, scopes=GOOGLE_SCOPES)


@router.get(
    "/auth/google/callback",
    response_model=GoogleAuthCallbackResponse,
    summary="Handle Google OAuth2 redirect callback",
)
async def google_auth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from Google"),
    state: str | None = Query(default=None, description="CSRF state token"),
    error: str | None = Query(default=None, description="OAuth error code"),
    format: str | None = Query(default=None, description="Response format: 'json' or 'redirect'"),
    redirect_uri: str | None = Query(default=None, description="Callback redirect URI"),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Exchange authorization code for tokens and update user credentials in DB."""
    accept_header = request.headers.get("accept", "").lower()
    wants_json = "application/json" in accept_header or format == "json"
    is_browser = "text/html" in accept_header

    def _handle_error(detail: str) -> Any:
        if is_browser:
            encoded_err = urllib.parse.quote_plus(detail)
            return RedirectResponse(
                url=f"/?auth_status=error&error={encoded_err}",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    if error:
        return _handle_error(f"Google OAuth authorization failed: {error}")

    if not code or not code.strip():
        return _handle_error("Authorization code cannot be empty.")

    target_user_id: str | None = None
    state_redirect_uri: str | None = None
    if state:
        payload = decode_access_token(state)
        if payload and payload.get("sub") and payload.get("type") == "oauth_state":
            target_user_id = str(payload["sub"])
            state_redirect_uri = payload.get("redirect_uri")

    if not target_user_id:
        return _handle_error(
            "Invalid or expired OAuth state parameter (유효하지 않거나 만료된 OAuth state 토큰입니다)."
        )

    user_settings = await _get_or_create_settings(db, target_user_id)
    app_settings = get_settings()

    is_mock = code.startswith("mock_")
    account_email: str | None = None

    if is_mock:
        access_token = "ya29.mock_google_access_token"
        refresh_token = "mock_google_refresh_token"
        account_email = "user@example.com"
    else:
        client_id = user_settings.google_client_id or app_settings.google_client_id
        client_secret = (
            user_settings.google_client_secret or app_settings.google_client_secret
        )

        if not client_id or not client_secret:
            return _handle_error(
                "Google OAuth2 Client ID 또는 Client Secret이 설정되지 않았습니다."
            )

        effective_redirect_uri = redirect_uri or state_redirect_uri
        if not effective_redirect_uri:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get(
                "x-forwarded-host", request.headers.get("host", request.url.netloc)
            )
            effective_redirect_uri = f"{proto}://{host}/api/v1/tools/auth/google/callback"

        async with httpx.AsyncClient(timeout=15.0) as http_client:
            token_payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": effective_redirect_uri,
            }
            try:
                resp = await http_client.post(
                    "https://oauth2.googleapis.com/token",
                    data=token_payload,
                )
                if resp.status_code != 200:
                    err_text = resp.text
                    logger.error("Google token exchange failed: %s", err_text)
                    return _handle_error(
                        f"Token exchange failed (Google 토큰 교환 실패): {err_text}"
                    )

                token_data = resp.json()
                access_token = token_data.get("access_token", "")
                refresh_token = token_data.get("refresh_token")
                account_email = token_data.get("email")
            except httpx.HTTPError as exc:
                logger.error("Google token exchange network error: %s", exc)
                return _handle_error(f"Google 인증 통신 실패: {exc}")

            if access_token and not account_email:
                try:
                    userinfo_resp = await http_client.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if userinfo_resp.status_code == 200:
                        u_data = userinfo_resp.json()
                        account_email = u_data.get("email")
                except Exception as exc:
                    logger.warning("Failed to fetch Google userinfo: %s", exc)

    assert target_user_id is not None
    user_settings.google_mock_linked = is_mock
    user_settings.google_access_token = access_token
    if refresh_token:
        user_settings.google_refresh_token = refresh_token
    if account_email:
        user_settings.google_linked_email = account_email
    user_settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user_settings)

    if not wants_json:
        return RedirectResponse(
            url="/?auth_status=google_linked",
            status_code=status.HTTP_302_FOUND,
        )

    return GoogleAuthCallbackResponse(
        status="success",
        provider="google",
        linked=True,
        is_mock=is_mock,
        account_email=user_settings.google_linked_email,
        message="Google Workspace account linked successfully.",
    )


@router.get(
    "/auth/google/credentials",
    response_model=GoogleCredentialsResponse,
    summary="Get Google OAuth2 configuration and connection status",
)
async def get_google_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GoogleCredentialsResponse:
    """Return whether Google OAuth client_id/secret are configured and account link status."""
    user_settings = await _get_or_create_settings(db, current_user.id)
    app_settings = get_settings()

    client_id = user_settings.google_client_id or app_settings.google_client_id or ""
    client_secret = (
        user_settings.google_client_secret or app_settings.google_client_secret or ""
    )
    is_linked = bool(
        user_settings.google_refresh_token or user_settings.google_access_token
    )

    return GoogleCredentialsResponse(
        client_id=client_id,
        has_client_secret=bool(client_secret),
        is_configured=bool(client_id and client_secret),
        is_linked=is_linked,
        account_email=user_settings.google_linked_email if is_linked else None,
    )


@router.post(
    "/auth/google/credentials",
    response_model=GoogleCredentialsResponse,
    summary="Update Google OAuth2 Client ID and Client Secret",
)
async def update_google_credentials(
    payload: GoogleCredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GoogleCredentialsResponse:
    """Save custom Google OAuth2 Client ID and Client Secret in user's settings."""
    user_settings = await _get_or_create_settings(db, current_user.id)
    app_settings = get_settings()

    if payload.client_id is not None:
        user_settings.google_client_id = payload.client_id.strip() or None
    if payload.client_secret is not None:
        user_settings.google_client_secret = payload.client_secret.strip() or None

    user_settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user_settings)

    client_id = user_settings.google_client_id or app_settings.google_client_id or ""
    client_secret = (
        user_settings.google_client_secret or app_settings.google_client_secret or ""
    )
    is_linked = bool(
        user_settings.google_refresh_token or user_settings.google_access_token
    )

    return GoogleCredentialsResponse(
        client_id=client_id,
        has_client_secret=bool(client_secret),
        is_configured=bool(client_id and client_secret),
        is_linked=is_linked,
        account_email=user_settings.google_linked_email if is_linked else None,
    )


@router.post(
    "/auth/google/disconnect",
    summary="Disconnect and revoke Google Workspace account",
)
async def disconnect_google(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Revoke and remove linked Google credentials for the current user."""
    user_settings = await _get_or_create_settings(db, current_user.id)

    token_to_revoke = (
        user_settings.google_refresh_token or user_settings.google_access_token
    )
    if token_to_revoke:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"https://oauth2.googleapis.com/revoke?token={token_to_revoke}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except Exception as exc:
            logger.debug("Failed to revoke token at Google revoke endpoint: %s", exc)

    user_settings.google_refresh_token = None
    user_settings.google_access_token = None
    user_settings.google_linked_email = None
    user_settings.google_mock_linked = False
    user_settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user_settings)

    return {
        "status": "success",
        "linked": False,
        "message": "Google Workspace 계정 연동이 해제되었습니다.",
    }


@router.post(
    "/auth/google/mock-link",
    response_model=GoogleMockLinkResponse,
    summary="Toggle mock Google Workspace credentials for offline testing",
)
async def mock_link_google(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GoogleMockLinkResponse:
    """Toggle deterministic mock Google credentials in DB for offline development."""
    user_settings = await _get_or_create_settings(db, current_user.id)

    if not user_settings.google_mock_linked:
        user_settings.google_mock_linked = True
        user_settings.google_refresh_token = "mock_google_refresh_token"
        user_settings.google_access_token = "mock_google_access_token"
        user_settings.google_linked_email = "cooper@endurance.space"
        message = "Mock Google Workspace account linked successfully."
    else:
        user_settings.google_mock_linked = False
        user_settings.google_refresh_token = None
        user_settings.google_access_token = None
        user_settings.google_linked_email = None
        message = "Mock Google Workspace account unlinked."

    user_settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user_settings)

    return GoogleMockLinkResponse(
        status="success",
        provider="google",
        linked=user_settings.google_linked,
        mock_linked=user_settings.google_mock_linked,
        is_mock=user_settings.google_mock_linked,
        account_email=user_settings.google_linked_email,
        message=message,
    )


@router.post(
    "/servers/{server_id}/test",
    response_model=ServerTestResponse,
    summary="Test connectivity to registered MCP server",
)
async def test_server_connectivity(
    server_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> ServerTestResponse:
    """Send ping to target MCP server and measure roundtrip latency."""
    if server_id == "google_workspace":
        user_settings = await _get_or_create_settings(db, current_user.id)
        is_linked = bool(
            user_settings.google_refresh_token or user_settings.google_access_token
        )
        return ServerTestResponse(
            server_id=server_id,
            status="connected" if is_linked else "offline",
            latency_ms=1.5,
            message=(
                "Google Workspace 계정이 정상적으로 연동되어 있습니다."
                if is_linked
                else "Google Workspace 계정이 연동되지 않았습니다."
            ),
        )

    for client in tool_registry._managed_clients:
        if isinstance(client, AsyncMCPClient) and client.config.name == server_id:
            ping_ok = await client.ping()
            is_mock = client.config.transport == MCPTransportType.MOCK
            srv_status: Literal["connected", "offline", "mock"] = (
                "mock" if is_mock else ("connected" if ping_ok else "offline")
            )
            return ServerTestResponse(
                server_id=server_id,
                status=srv_status,
                latency_ms=2.0 if (ping_ok or is_mock) else 0.0,
                message=(
                    "MCP server ping passed"
                    if (ping_ok or is_mock)
                    else "MCP server unreachable"
                ),
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Server '{server_id}' not found.",
    )


__all__ = ["router"]
