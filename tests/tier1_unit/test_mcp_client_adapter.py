"""Tier 1 Unit Tests: Model Context Protocol (MCP) Client and Tool Adapter.

Tests:
1. AsyncMCPClient connection, tool listing, tool invocation, and mock handlers.
2. MCPToolAdapter schema conversion and asynchronous execution.
3. register_mcp_server_tools dynamic registry discovery and prefixing.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
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


# ============================================================================
# 4. REL-03: Fault Tolerance, Exponential Backoff & Execution Timeout Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_client_retry_on_transient_http_502_503_504() -> None:
    """Verify AsyncMCPClient retries with exponential backoff on 502/503/504 errors (REL-03)."""
    tool_call_count = 0

    def transient_handler(request: httpx.Request) -> httpx.Response:
        nonlocal tool_call_count
        import json

        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {"name": "test"}}},
            )
        tool_call_count += 1
        if tool_call_count == 1:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "Recovered successfully"}],
                    "isError": False,
                },
            },
        )

    mock_transport = httpx.MockTransport(transient_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    client = AsyncMCPClient(
        config=MCPServerConfig(
            name="retry_mcp", transport=MCPTransportType.HTTP, url="http://mcp.test/rpc"
        ),
        http_client=http_client,
    )

    sleep_delays: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        res = await client.call_tool("flaky_tool", {"param": 1})
        assert res.isError is False
        assert "Recovered successfully" in res.text
        # Verified attempt 0 failed with 502, slept 0.5s, attempt 1 succeeded
        assert len(sleep_delays) == 1
        assert sleep_delays[0] == 0.5
        assert tool_call_count == 2

    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_retry_exhaustion_on_connect_error() -> None:
    """Verify AsyncMCPClient exhausts max 2 retries on ConnectError (3 total attempts) (REL-03)."""
    attempt_count = 0

    def error_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt_count
        import json

        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {"name": "test"}}},
            )
        attempt_count += 1
        raise httpx.ConnectError("Connection refused by target machine", request=request)

    mock_transport = httpx.MockTransport(error_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    client = AsyncMCPClient(
        config=MCPServerConfig(
            name="down_mcp", transport=MCPTransportType.HTTP, url="http://mcp.test/rpc"
        ),
        http_client=http_client,
    )

    sleep_delays: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    with patch("asyncio.sleep", side_effect=mock_sleep):
        res = await client.call_tool("down_tool", {})
        assert res.isError is True
        assert "MCP tool network failure" in res.text
        # Max retries = 2: attempt 0 (sleep 0.5), attempt 1 (sleep 1.0), attempt 2 (final, no sleep)
        assert attempt_count == 3
        assert sleep_delays == [0.5, 1.0]

    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_execution_timeout_guard() -> None:
    """Verify AsyncMCPClient enforces execution timeout guard and returns error result (REL-03)."""
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {"name": "test"}}},
            )
        await asyncio.sleep(5.0)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}})

    mock_transport = httpx.MockTransport(slow_handler)
    http_client = httpx.AsyncClient(transport=mock_transport)
    client = AsyncMCPClient(
        config=MCPServerConfig(
            name="hanging_mcp", transport=MCPTransportType.HTTP, url="http://mcp.test/rpc"
        ),
        http_client=http_client,
    )

    import time

    start = time.monotonic()
    res = await client.call_tool("slow_tool", {}, timeout=0.1)
    duration = time.monotonic() - start

    assert duration < 0.5
    assert res.isError is True
    assert "timed out after 0.1s" in res.text

    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_mock_transport_timeout_guard() -> None:
    """Verify AsyncMCPClient execution timeout guard also applies to Mock transport handlers (REL-03)."""
    config = MCPServerConfig(name="mock_timeout_mcp", transport=MCPTransportType.MOCK)
    client = AsyncMCPClient(config=config)

    meta = MCPToolMeta(name="hanging_mock", description="Hangs", inputSchema={"type": "object"})

    async def hanging_handler() -> str:
        await asyncio.sleep(5.0)
        return "Should not finish"

    client.register_mock_tool(meta, handler=hanging_handler)

    import time

    start = time.monotonic()
    res = await client.call_tool("hanging_mock", {}, timeout=0.1)
    duration = time.monotonic() - start

    assert duration < 0.5
    assert res.isError is True
    assert "timed out after 0.1s" in res.text

    await client.close()
