"""Model Context Protocol (MCP) integration package for TARS."""

from tars.domains.tools.mcp.adapter import MCPToolAdapter, register_mcp_server_tools
from tars.domains.tools.mcp.client import AsyncMCPClient
from tars.domains.tools.mcp.models import (
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
