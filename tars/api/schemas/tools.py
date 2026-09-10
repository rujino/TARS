"""Pydantic request and response schemas for TARS Tool & MCP endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


__all__ = [
    "GoogleAuthCallbackResponse",
    "GoogleAuthUrlResponse",
    "GoogleCredentialsRequest",
    "GoogleCredentialsResponse",
    "GoogleMockLinkResponse",
    "ServerInfo",
    "ServerTestResponse",
    "ToolItem",
    "ToolToggleRequest",
    "ToolToggleResponse",
    "ToolsServersResponse",
]
