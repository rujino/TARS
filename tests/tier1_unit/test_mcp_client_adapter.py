"""Tier 1 Unit Tests: Model Context Protocol (MCP) Client and Tool Adapter.

Tests:
1. AsyncMCPClient connection, tool listing, tool invocation, and mock handlers.
2. MCPToolAdapter schema conversion and asynchronous execution.
3. register_mcp_server_tools dynamic registry discovery and prefixing.
"""

from __future__ import annotations

from typing import Any

import pytest

from tars.tools.mcp.adapter import MCPToolAdapter, register_mcp_server_tools
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import (
    MCPServerConfig,
    MCPToolMeta,
    MCPTransportType,
)
from tars.tools.registry import ToolRegistry

# ============================================================================
# 1. AsyncMCPClient Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_client_mock_lifecycle_and_tools_list() -> None:
    """Verify AsyncMCPClient mock connection, tool registration, and list_tools."""
    config = MCPServerConfig(
        name="test_weather_mcp",
        transport=MCPTransportType.MOCK,
    )
    client = AsyncMCPClient(config=config)

    # Register mock tools
    weather_tool_meta = MCPToolMeta(
        name="get_current_weather",
        description="Get current temperature and conditions for a city.",
        inputSchema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"], "default": "celsius"},
            },
            "required": ["location"],
        },
    )
    client.register_mock_tool(weather_tool_meta)

    # Connect
    init_res = await client.connect()
    assert init_res["serverInfo"]["name"] == "test_weather_mcp"

    # List tools
    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "get_current_weather"
    assert "location" in tools[0].inputSchema["properties"]

    # Ping
    is_alive = await client.ping()
    assert is_alive is True

    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_tool_invocation_and_handlers() -> None:
    """Verify AsyncMCPClient executes tools with custom handlers and handles errors."""
    config = MCPServerConfig(name="test_calc_mcp", transport=MCPTransportType.MOCK)
    client = AsyncMCPClient(config=config)

    # Register calculate tool with custom handler
    def custom_calc_handler(x: int, y: int, op: str = "+") -> dict[str, Any]:
        if op == "+":
            return {"result": x + y}
        if op == "*":
            return {"result": x * y}
        raise ValueError(f"Unsupported operator: {op}")

    client.register_mock_tool(
        MCPToolMeta(
            name="calculate",
            description="Perform arithmetic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "op": {"type": "string"},
                },
                "required": ["x", "y"],
            },
        ),
        handler=custom_calc_handler,
    )

    # 1. Success execution
    res = await client.call_tool("calculate", {"x": 7, "y": 6, "op": "*"})
    assert res.isError is False
    assert res.structured_data == {"result": 42}

    # 2. Error handling in handler
    err_res = await client.call_tool("calculate", {"x": 7, "y": 6, "op": "invalid_op"})
    assert err_res.isError is True
    assert "Unsupported operator" in err_res.text

    # 3. Calling nonexistent tool returns error
    missing_res = await client.call_tool("nonexistent_tool", {})
    assert missing_res.isError is True


# ============================================================================
# 2. MCPToolAdapter Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_tool_adapter_wrapping_and_execution() -> None:
    """Verify MCPToolAdapter wraps MCPToolMeta into BaseTool and executes."""
    config = MCPServerConfig(name="test_mcp", transport=MCPTransportType.MOCK)
    client = AsyncMCPClient(config=config)

    meta = MCPToolMeta(
        name="lookup_system_status",
        description="Fetch current status of Endurance systems.",
        inputSchema={
            "type": "object",
            "properties": {"subsystem": {"type": "string"}},
            "required": ["subsystem"],
        },
    )

    async def status_handler(subsystem: str) -> dict[str, Any]:
        return {"subsystem": subsystem, "status": "nominal", "integrity": "100%"}

    client.register_mock_tool(meta, handler=status_handler)

    adapter = MCPToolAdapter(client=client, meta=meta, prefix="mcp")
    assert adapter.name == "mcp_lookup_system_status"
    assert adapter.description == "Fetch current status of Endurance systems."
    assert "subsystem" in adapter.parameters_schema["properties"]

    # Gemini declaration
    decl = adapter.to_gemini_declaration()
    assert decl["name"] == "mcp_lookup_system_status"

    # Execute
    result = await adapter.aexecute(subsystem="propulsion")
    assert result == {"subsystem": "propulsion", "status": "nominal", "integrity": "100%"}


@pytest.mark.asyncio
async def test_mcp_tool_adapter_error_raises_runtime_error() -> None:
    """Verify MCPToolAdapter raises RuntimeError on MCP error response."""
    config = MCPServerConfig(name="test_mcp", transport=MCPTransportType.MOCK)
    client = AsyncMCPClient(config=config)

    meta = MCPToolMeta(name="failing_mcp_tool", description="Fails", inputSchema={"type": "object"})

    def failing_handler() -> Any:
        raise RuntimeError("Subsystem connection lost.")

    client.register_mock_tool(meta, handler=failing_handler)
    adapter = MCPToolAdapter(client=client, meta=meta)

    with pytest.raises(RuntimeError, match="Subsystem connection lost"):
        await adapter.aexecute()


# ============================================================================
# 3. Dynamic ToolRegistry Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_register_mcp_server_tools_into_registry() -> None:
    """Verify registering all tools from an MCP server directly into ToolRegistry."""
    config = MCPServerConfig(name="endurance_telemetry", transport=MCPTransportType.MOCK)
    client = AsyncMCPClient(config=config)

    t1 = MCPToolMeta(name="get_speed", description="Get velocity", inputSchema={"type": "object"})
    t2 = MCPToolMeta(name="get_gravity", description="Get gravity", inputSchema={"type": "object"})
    client.register_mock_tool(t1, handler=lambda: "0.8c")
    client.register_mock_tool(t2, handler=lambda: "1.3g")

    registry = ToolRegistry()
    registered_adapters = await register_mcp_server_tools(
        client=client,
        registry=registry,
        prefix="endurance",
    )

    assert len(registered_adapters) == 2
    assert registry.has_tool("endurance_get_speed")
    assert registry.has_tool("endurance_get_gravity")

    # Execute through registry
    speed_res = await registry.execute_tool("endurance_get_speed", {})
    assert speed_res == "0.8c"
    grav_res = await registry.execute_tool("endurance_get_gravity", {})
    assert grav_res == "1.3g"
