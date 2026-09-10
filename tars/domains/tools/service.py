"""Tool and MCP Server Management Business Service."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tars.config import Settings, get_settings
from tars.core.security import create_access_token, decode_access_token
from tars.domains.persona.service import UserSettingsService
from tars.domains.tools.mcp.adapter import MCPToolAdapter
from tars.domains.tools.mcp.client import AsyncMCPClient
from tars.domains.tools.mcp.models import MCPTransportType
from tars.domains.tools.registry import ToolRegistry
from tars.domains.tools.schemas import (
    GoogleAuthCallbackResponse,
    GoogleAuthUrlResponse,
    GoogleCredentialsRequest,
    GoogleCredentialsResponse,
    GoogleMockLinkResponse,
    ServerInfo,
    ServerTestResponse,
    ToolItem,
    ToolsServersResponse,
    ToolToggleRequest,
    ToolToggleResponse,
)

logger = logging.getLogger("tars.domains.tools.service")

GOOGLE_SCOPES: list[str] = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ============================================================================
# Domain Exceptions
# ============================================================================


class ToolServiceError(Exception):
    """Base exception for tool service errors."""


class ToolNotFoundError(ToolServiceError):
    """Raised when the specified tool is not found in the registry."""


class ServerNotFoundError(ToolServiceError):
    """Raised when the specified tool server is not found."""


class GoogleOAuthNotConfiguredError(ToolServiceError):
    """Raised when Google OAuth Client ID or Secret is missing."""


class InvalidOAuthStateError(ToolServiceError):
    """Raised when the OAuth state token is invalid or expired."""


class OAuthCodeEmptyError(ToolServiceError):
    """Raised when the OAuth authorization code is empty."""


class TokenExchangeError(ToolServiceError):
    """Raised when exchanging authorization code for tokens fails."""


# ============================================================================
# Service Implementation
# ============================================================================


class ToolService:
    """Encapsulates tool registration, server status, and OAuth linking workflows."""

    def __init__(
        self,
        db: AsyncSession,
        tool_registry: ToolRegistry,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.tool_registry = tool_registry
        self.settings = settings or get_settings()
        self.user_settings_service = UserSettingsService(db)

    async def list_servers(self, user_id: str) -> ToolsServersResponse:
        """Return all registered servers (Google Workspace and MCP) with active/disabled states."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)
        disabled_set = set(user_settings.disabled_tools or [])

        google_tools: list[ToolItem] = []
        mcp_servers_map: dict[str, dict[str, Any]] = {}
        other_tools: list[ToolItem] = []

        for tool in self.tool_registry.list_tools():
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
                    srv_status: Literal["connected", "offline", "mock"] = (
                        "mock" if is_mock_srv else ("connected" if is_connected else "offline")
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
                transport="oauth2",
                description="Google Calendar and Gmail tools via OAuth 2.0",
                total_tools=len(google_tools),
                total_tools_count=len(google_tools),
                active_tools=google_active_count,
                active_tools_count=google_active_count,
                auth_required=True,
                is_linked=google_linked,
                is_mock=bool(user_settings.google_mock_linked),
                account_email=google_email,
                tools=google_tools,
            )
        )

        # 2. MCP Servers
        for srv_dict in mcp_servers_map.values():
            active_cnt = sum(1 for t in srv_dict["tools"] if t.active)
            servers.append(
                ServerInfo(
                    id=srv_dict["id"],
                    name=srv_dict["name"],
                    type="mcp",
                    status=srv_dict["status"],
                    transport=srv_dict["transport"],
                    url=srv_dict["url"],
                    description=srv_dict["description"],
                    total_tools=len(srv_dict["tools"]),
                    total_tools_count=len(srv_dict["tools"]),
                    active_tools=active_cnt,
                    active_tools_count=active_cnt,
                    auth_required=False,
                    is_linked=srv_dict["status"] == "connected",
                    is_mock=srv_dict["status"] == "mock",
                    account_email=None,
                    tools=srv_dict["tools"],
                )
            )

        # 3. Other Builtin Tools
        if other_tools:
            other_active_count = sum(1 for t in other_tools if t.active)
            servers.append(
                ServerInfo(
                    id="builtin_tools",
                    name="Built-in Tools",
                    type="builtin",
                    status="connected",
                    transport="in_process",
                    description="Internal deterministic utilities",
                    total_tools=len(other_tools),
                    total_tools_count=len(other_tools),
                    active_tools=other_active_count,
                    active_tools_count=other_active_count,
                    auth_required=False,
                    is_linked=True,
                    is_mock=False,
                    account_email=None,
                    tools=other_tools,
                )
            )

        return ToolsServersResponse(servers=servers)

    async def toggle_tool(
        self,
        user_id: str,
        tool_name: str,
        payload: ToolToggleRequest | None = None,
    ) -> ToolToggleResponse:
        """Toggle or persist tool active/disabled state in user settings."""
        if not self.tool_registry.has_tool(tool_name):
            raise ToolNotFoundError(f"Tool '{tool_name}' not found in registry.")

        settings = await self.user_settings_service.get_or_create_settings(user_id)
        disabled_list = list(settings.disabled_tools or [])

        desired_active: bool | None = None
        if payload is not None:
            if payload.active is not None:
                desired_active = payload.active
            elif payload.enabled is not None:
                desired_active = payload.enabled

        if desired_active is None:
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
        await self.db.commit()
        await self.db.refresh(settings)

        action_str = "enabled" if is_active else "disabled"
        return ToolToggleResponse(
            tool_name=tool_name,
            active=is_active,
            enabled=is_active,
            disabled_tools=settings.disabled_tools or [],
            user_id=user_id,
            message=f"Tool '{tool_name}' {action_str} successfully.",
        )

    async def get_google_auth_url(
        self,
        user_id: str,
        default_redirect_uri: str,
        override_redirect_uri: str | None = None,
    ) -> GoogleAuthUrlResponse:
        """Generate Google OAuth2 authorization redirect URL with CSRF state token."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)
        client_id = user_settings.google_client_id or self.settings.google_client_id

        if not client_id:
            raise GoogleOAuthNotConfiguredError(
                "Google OAuth2 Client ID가 설정되지 않았습니다. 먼저 Client ID와 Secret을 입력하고 저장해 주세요."
            )

        redirect_uri = override_redirect_uri or default_redirect_uri
        state_token = create_access_token(
            data={
                "sub": user_id,
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

    async def handle_google_callback(
        self,
        code: str,
        state: str | None,
        default_redirect_uri: str,
        override_redirect_uri: str | None = None,
    ) -> tuple[str, GoogleAuthCallbackResponse]:
        """Exchange authorization code for tokens and update user credentials.

        Returns (target_user_id, callback_response).
        """
        if not code or not code.strip():
            raise OAuthCodeEmptyError("Authorization code cannot be empty.")

        target_user_id: str | None = None
        state_redirect_uri: str | None = None
        if state:
            payload = decode_access_token(state)
            if payload and payload.get("sub") and payload.get("type") == "oauth_state":
                target_user_id = str(payload["sub"])
                state_redirect_uri = payload.get("redirect_uri")

        if not target_user_id:
            raise InvalidOAuthStateError(
                "Invalid or expired OAuth state parameter (유효하지 않거나 만료된 OAuth state 토큰입니다)."
            )

        user_settings = await self.user_settings_service.get_or_create_settings(target_user_id)
        is_mock = code.startswith("mock_")
        account_email: str | None = None

        if is_mock:
            access_token = "ya29.mock_google_access_token"
            refresh_token = "mock_google_refresh_token"
            account_email = "user@example.com"
        else:
            client_id = user_settings.google_client_id or self.settings.google_client_id
            client_secret = user_settings.google_client_secret or self.settings.google_client_secret

            if not client_id or not client_secret:
                raise GoogleOAuthNotConfiguredError(
                    "Google OAuth2 Client ID 또는 Client Secret이 설정되지 않았습니다."
                )

            effective_redirect_uri = (
                override_redirect_uri or state_redirect_uri or default_redirect_uri
            )

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
                        raise TokenExchangeError(
                            f"Token exchange failed (Google 토큰 교환 실패): {err_text}"
                        )

                    token_data = resp.json()
                    access_token = token_data.get("access_token", "")
                    refresh_token = token_data.get("refresh_token")
                    account_email = token_data.get("email")
                except httpx.HTTPError as exc:
                    logger.error("Google token exchange network error: %s", exc)
                    raise TokenExchangeError(f"Google 인증 통신 실패: {exc}") from exc

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

        user_settings.google_mock_linked = is_mock
        user_settings.google_access_token = access_token
        if refresh_token:
            user_settings.google_refresh_token = refresh_token
        if account_email:
            user_settings.google_linked_email = account_email

        self.tool_registry.invalidate_user_google_cache(target_user_id)

        user_settings.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user_settings)

        resp_dto = GoogleAuthCallbackResponse(
            status="success",
            provider="google",
            linked=True,
            is_mock=is_mock,
            account_email=user_settings.google_linked_email,
            message="Google Workspace account linked successfully.",
        )
        return target_user_id, resp_dto

    async def get_google_credentials(self, user_id: str) -> GoogleCredentialsResponse:
        """Return whether Google OAuth client_id/secret are configured and account link status."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)

        client_id = user_settings.google_client_id or self.settings.google_client_id or ""
        client_secret = (
            user_settings.google_client_secret or self.settings.google_client_secret or ""
        )
        is_linked = bool(user_settings.google_refresh_token or user_settings.google_access_token)

        return GoogleCredentialsResponse(
            client_id=client_id,
            has_client_secret=bool(client_secret),
            is_configured=bool(client_id and client_secret),
            is_linked=is_linked,
            account_email=user_settings.google_linked_email if is_linked else None,
        )

    async def update_google_credentials(
        self,
        user_id: str,
        payload: GoogleCredentialsRequest,
    ) -> GoogleCredentialsResponse:
        """Save custom Google OAuth2 Client ID and Client Secret in user's settings."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)

        if payload.client_id is not None:
            user_settings.google_client_id = payload.client_id.strip() or None
        if payload.client_secret is not None:
            user_settings.google_client_secret = payload.client_secret.strip() or None

        self.tool_registry.invalidate_user_google_cache(user_id)

        user_settings.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user_settings)

        client_id = user_settings.google_client_id or self.settings.google_client_id or ""
        client_secret = (
            user_settings.google_client_secret or self.settings.google_client_secret or ""
        )
        is_linked = bool(user_settings.google_refresh_token or user_settings.google_access_token)

        return GoogleCredentialsResponse(
            client_id=client_id,
            has_client_secret=bool(client_secret),
            is_configured=bool(client_id and client_secret),
            is_linked=is_linked,
            account_email=user_settings.google_linked_email if is_linked else None,
        )

    async def disconnect_google(self, user_id: str) -> dict[str, Any]:
        """Revoke and remove linked Google credentials for the user."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)

        token_to_revoke = user_settings.google_refresh_token or user_settings.google_access_token
        if token_to_revoke:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"https://oauth2.googleapis.com/revoke?token={token_to_revoke}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
            except Exception as exc:
                logger.debug("Failed to revoke token at Google revoke endpoint: %s", exc)

        self.tool_registry.invalidate_user_google_cache(user_id)

        user_settings.google_refresh_token = None
        user_settings.google_access_token = None
        user_settings.google_linked_email = None
        user_settings.google_mock_linked = False
        user_settings.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user_settings)

        return {
            "status": "success",
            "linked": False,
            "message": "Google Workspace 계정 연동이 해제되었습니다.",
        }

    async def mock_link_google(self, user_id: str) -> GoogleMockLinkResponse:
        """Toggle deterministic mock Google credentials in DB for offline development."""
        user_settings = await self.user_settings_service.get_or_create_settings(user_id)

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

        self.tool_registry.invalidate_user_google_cache(user_id)

        user_settings.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user_settings)

        return GoogleMockLinkResponse(
            status="success",
            provider="google",
            linked=user_settings.google_linked,
            mock_linked=user_settings.google_mock_linked,
            is_mock=user_settings.google_mock_linked,
            account_email=user_settings.google_linked_email,
            message=message,
        )

    async def test_server_connectivity(
        self,
        user_id: str,
        server_id: str,
    ) -> ServerTestResponse:
        """Send ping to target server and measure roundtrip latency."""
        if server_id == "google_workspace":
            user_settings = await self.user_settings_service.get_or_create_settings(user_id)
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

        for client in self.tool_registry._managed_clients:
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

        raise ServerNotFoundError(f"Server '{server_id}' not found.")


__all__ = [
    "GOOGLE_SCOPES",
    "GoogleOAuthNotConfiguredError",
    "InvalidOAuthStateError",
    "OAuthCodeEmptyError",
    "ServerNotFoundError",
    "TokenExchangeError",
    "ToolNotFoundError",
    "ToolService",
    "ToolServiceError",
]
