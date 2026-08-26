"""Model Context Protocol (MCP) integration package for TARS."""

from tars.tools.mcp.adapter import MCPToolAdapter, register_mcp_server_tools
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import (
    MCPCallResult,
    MCPServerConfig,
    MCPToolMeta,
    MCPTransportType,
)

__all__ = [
    "AsyncMCPClient",
    "MCPCallResult",
    "MCPServerConfig",
    "MCPToolAdapter",
    "MCPToolMeta",
    "MCPTransportType",
    "register_mcp_server_tools",
]
