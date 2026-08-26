"""MCP Tool Adapter wrapping remote MCP tools as TARS BaseTool instances."""

from __future__ import annotations

import logging
from typing import Any

from tars.tools.base import BaseTool
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import MCPToolMeta
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.tools.mcp.adapter")


class MCPToolAdapter(BaseTool):
    """Adapter wrapping an individual MCP server tool as a native TARS BaseTool."""

    def __init__(
        self,
        client: AsyncMCPClient,
        meta: MCPToolMeta,
        prefix: str = "",
    ) -> None:
        self.client = client
        self.meta = meta
        self._original_name = meta.name
        tool_name = f"{prefix}_{meta.name}" if prefix else meta.name
        super().__init__(
            name=tool_name,
            description=meta.description,
            parameters_schema=meta.inputSchema,
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute the remote MCP tool and return result or raise on error.

        Args:
            **kwargs: Arguments corresponding to tool inputSchema.

        Returns:
            Extracted text or structured dictionary result.

        Raises:
            RuntimeError: If remote tool call flagged an error.
        """
        result = await self.client.call_tool(name=self._original_name, arguments=kwargs)
        if result.isError:
            err_msg = result.text or "Remote MCP tool execution returned an error."
            raise RuntimeError(err_msg)

        if result.structured_data is not None:
            return result.structured_data
        return result.text


async def register_mcp_server_tools(
    client: AsyncMCPClient,
    registry: ToolRegistry,
    prefix: str = "",
) -> list[MCPToolAdapter]:
    """Discover and register all tools from an MCP client into the target ToolRegistry.

    Args:
        client: Connected AsyncMCPClient.
        registry: TARS ToolRegistry instance.
        prefix: Optional prefix for registered tool names.

    Returns:
        List of registered MCPToolAdapter instances.
    """
    tools_meta = await client.list_tools()
    adapters: list[MCPToolAdapter] = []
    for meta in tools_meta:
        adapter = MCPToolAdapter(client=client, meta=meta, prefix=prefix)
        registry.register(adapter)
        adapters.append(adapter)
        logger.info(
            "Registered MCP tool adapter: %s (from server %s)", adapter.name, client.config.name
        )
    return adapters


__all__ = [
    "MCPToolAdapter",
    "register_mcp_server_tools",
]
