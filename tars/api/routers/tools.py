"""TARS Tool and MCP Server Management REST Router.

Thin Controller pattern: Delegates tool inventory, state toggles, and OAuth linking to ToolService.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.dependencies import (
    get_current_user,
    get_db_session,
    get_tool_registry,
    get_tool_service,
)
from tars.api.schemas.tools import (
    GoogleAuthCallbackResponse,
    GoogleAuthUrlResponse,
    GoogleCredentialsRequest,
    GoogleCredentialsResponse,
    GoogleMockLinkResponse,
    ServerTestResponse,
    ToolsServersResponse,
    ToolToggleRequest,
    ToolToggleResponse,
)
from tars.config import get_settings
from tars.db.models import User
from tars.services.tool_service import (
    GoogleOAuthNotConfiguredError,
    InvalidOAuthStateError,
    OAuthCodeEmptyError,
    ServerNotFoundError,
    TokenExchangeError,
    ToolNotFoundError,
    ToolService,
)
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.routers.tools")
router = APIRouter(prefix="/tools", tags=["Tools Management"])


def _resolve_tool_service(
    tool_service: Any,
    db: AsyncSession | None,
    tool_registry: ToolRegistry | None,
) -> ToolService:
    """Helper ensuring ToolService is available either directly or from injected dependencies."""
    if isinstance(tool_service, ToolService):
        return tool_service
    if db is not None and tool_registry is not None:
        return ToolService(db=db, tool_registry=tool_registry, settings=get_settings())
    raise ValueError("Either tool_service or both db and tool_registry must be provided.")


@router.get(
    "/servers",
    response_model=ToolsServersResponse,
    summary="List all registered tool servers and their tools",
)
async def list_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> ToolsServersResponse:
    """Return all registered servers (Google Workspace and MCP servers) with active/disabled tool states."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    return await service.list_servers(current_user.id)


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
    tool_service: ToolService | None = Depends(get_tool_service),
) -> ToolToggleResponse:
    """Toggle or persist tool active/disabled state in current user's TARSSettings."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    try:
        return await service.toggle_tool(current_user.id, tool_name, payload)
    except ToolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
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
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> GoogleAuthUrlResponse:
    """Generate Google OAuth2 authorization redirect URL with required scopes and CSRF state token."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", request.url.netloc)
    )
    default_redirect_uri = f"{proto}://{host}/api/v1/tools/auth/google/callback"

    service = _resolve_tool_service(tool_service, db, tool_registry)
    try:
        return await service.get_google_auth_url(
            user_id=current_user.id,
            default_redirect_uri=default_redirect_uri,
            override_redirect_uri=redirect_uri,
        )
    except GoogleOAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


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
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
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

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get(
        "x-forwarded-host", request.headers.get("host", request.url.netloc)
    )
    default_redirect_uri = f"{proto}://{host}/api/v1/tools/auth/google/callback"

    service = _resolve_tool_service(tool_service, db, tool_registry)
    try:
        _, resp_dto = await service.handle_google_callback(
            code=code,
            state=state,
            default_redirect_uri=default_redirect_uri,
            override_redirect_uri=redirect_uri,
        )
    except (
        OAuthCodeEmptyError,
        InvalidOAuthStateError,
        GoogleOAuthNotConfiguredError,
        TokenExchangeError,
    ) as exc:
        return _handle_error(str(exc))

    if not wants_json:
        return RedirectResponse(
            url="/?auth_status=google_linked",
            status_code=status.HTTP_302_FOUND,
        )

    return resp_dto


@router.get(
    "/auth/google/credentials",
    response_model=GoogleCredentialsResponse,
    summary="Get Google OAuth2 configuration and connection status",
)
async def get_google_credentials(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> GoogleCredentialsResponse:
    """Return whether Google OAuth client_id/secret are configured and account link status."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    return await service.get_google_credentials(current_user.id)


@router.post(
    "/auth/google/credentials",
    response_model=GoogleCredentialsResponse,
    summary="Update Google OAuth2 Client ID and Client Secret",
)
async def update_google_credentials(
    payload: GoogleCredentialsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> GoogleCredentialsResponse:
    """Save custom Google OAuth2 Client ID and Client Secret in user's settings."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    return await service.update_google_credentials(current_user.id, payload)


@router.post(
    "/auth/google/disconnect",
    summary="Disconnect and revoke Google Workspace account",
)
async def disconnect_google(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> dict[str, Any]:
    """Revoke and remove linked Google credentials for the current user."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    return await service.disconnect_google(current_user.id)


@router.post(
    "/auth/google/mock-link",
    response_model=GoogleMockLinkResponse,
    summary="Toggle mock Google Workspace credentials for offline testing",
)
async def mock_link_google(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    tool_service: ToolService | None = Depends(get_tool_service),
) -> GoogleMockLinkResponse:
    """Toggle deterministic mock Google credentials in DB for offline development."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    return await service.mock_link_google(current_user.id)


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
    tool_service: ToolService | None = Depends(get_tool_service),
) -> ServerTestResponse:
    """Send ping to target MCP server and measure roundtrip latency."""
    service = _resolve_tool_service(tool_service, db, tool_registry)
    try:
        return await service.test_server_connectivity(current_user.id, server_id)
    except ServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


__all__ = [
    "GoogleCredentialsRequest",
    "get_settings",
    "mock_link_google",
    "router",
    "update_google_credentials",
]
