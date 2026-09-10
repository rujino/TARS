"""Model Context Protocol (MCP) data models and schema definitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPTransportType(StrEnum):
    """Transport protocol type for connecting to an MCP server."""

    SSE = "sse"
    STDIO = "stdio"
    HTTP = "http"
    MOCK = "mock"


class MCPServerConfig(BaseModel):
    """Configuration for connecting to an external MCP server."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Unique server name/identifier")
    transport: MCPTransportType = Field(
        default=MCPTransportType.SSE, description="Transport communication type"
    )
    url: str | None = Field(default=None, description="Endpoint URL for SSE or HTTP transports")
    command: str | None = Field(default=None, description="Executable command for Stdio transport")
    args: list[str] = Field(default_factory=list, description="Arguments for Stdio command")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables for Stdio subprocess"
    )
    timeout: float = Field(default=10.0, ge=1.0, le=300.0, description="Request timeout in seconds")


class MCPToolMeta(BaseModel):
    """Metadata specification for a tool exposed by an MCP server."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Tool name exposed by MCP server")
    description: str = Field(default="", description="Description of the tool function")
    inputSchema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
        description="JSON Schema for input arguments",
    )


class MCPCallResult(BaseModel):
    """Result of an MCP tools/call invocation."""

    model_config = ConfigDict(extra="ignore")

    content: list[dict[str, Any]] = Field(
        default_factory=list, description="List of content items (text, image, resource)"
    )
    isError: bool = Field(default=False, description="Whether the tool execution failed")
    structured_data: dict[str, Any] | list[Any] | None = Field(
        default=None, description="Structured parsed JSON payload if available"
    )

    @property
    def text(self) -> str:
        """Extract and concatenate all text elements from the result content."""
        texts: list[str] = []
        for item in self.content:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                texts.append(str(item["text"]))
        return "\n".join(texts)


__all__ = [
    "MCPCallResult",
    "MCPServerConfig",
    "MCPToolMeta",
    "MCPTransportType",
]
