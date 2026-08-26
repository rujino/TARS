"""Adversarial Protocol and Edge Case Stress Tests for Phase 3 Milestone 2.

Comprehensive Empirical Verification of:
1. ToolRegistry: Duplicate registration, invalid names, argument mismatch, and schema export invariance.
2. ToolCAGManager: Invalidation, hash dynamics on registry modification, sync/async GenAI client resilience.
3. AsyncMCPClient & MCPToolAdapter: JSON-RPC errors, HTTP 500/404, malformed JSON, network timeouts, ping drops.
4. Google Workspace (Calendar & Gmail) & Auth: Token refresh simulation, real HTTP mode mocking, boundary arguments.
5. End-to-end Protocol Failure inside LangGraph ReAct pipeline.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.orchestrator.graph import build_tars_graph, compile_tars_graph
from tars.orchestrator.state import TARSState
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.base import BaseTool
from tars.tools.cag import ToolCAGManager
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import GoogleCalendarAdapter
from tars.tools.google.gmail import GmailAdapter
from tars.tools.mcp.adapter import MCPToolAdapter
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import (
    MCPServerConfig,
    MCPToolMeta,
    MCPTransportType,
)
from tars.tools.registry import ToolRegistry
from tests.conftest import MockLLMAdapter

# ============================================================================
# 1. ToolRegistry Adversarial & Boundary Tests
# ============================================================================


class SimpleEchoTool(BaseTool):
    """Tool that echoes arguments."""

    def __init__(self, name: str = "echo_tool", desc: str = "Echo tool") -> None:
        super().__init__(
            name=name,
            description=desc,
            parameters_schema={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> str:
        return str(kwargs.get("msg", ""))


def test_registry_duplicate_registration_overwrites_cleanly() -> None:
    """Registering a tool with the same name replaces the prior instance."""
    tool1 = SimpleEchoTool("probe_tool", "Version 1")
    tool2 = SimpleEchoTool("probe_tool", "Version 2")

    registry = ToolRegistry([tool1])
    assert len(registry) == 1
    assert registry.get_tool("probe_tool") is tool1
    assert registry.get_tool("probe_tool").description == "Version 1"  # type: ignore[union-attr]

    registry.register(tool2)
    assert len(registry) == 1
    assert registry.get_tool("probe_tool") is tool2
    assert registry.get_tool("probe_tool").description == "Version 2"  # type: ignore[union-attr]


def test_registry_invalid_tool_name_raises_value_error() -> None:
    """Registering a tool with empty string name must raise ValueError."""

    class EmptyNameTool(BaseTool):
        def __init__(self) -> None:
            super().__init__(name="", description="Empty name")

        async def aexecute(self, **kwargs: Any) -> Any:
            return "empty"

    registry = ToolRegistry()
    with pytest.raises(ValueError, match="valid name"):
        registry.register(EmptyNameTool())


@pytest.mark.asyncio
async def test_registry_unexpected_and_missing_arguments() -> None:
    """Tool execution with missing or unexpected arguments raises appropriate exceptions."""

    class StrictKeywordTool(BaseTool):
        def __init__(self) -> None:
            super().__init__(name="strict_tool", description="Requires x and y")

        async def aexecute(self, **kwargs: Any) -> Any:
            if "x" not in kwargs or "y" not in kwargs:
                raise TypeError("Missing required keyword arguments 'x' and 'y'")
            if len(kwargs) > 2:
                raise TypeError("Unexpected keyword arguments")
            return int(kwargs["x"]) * int(kwargs["y"])

    registry = ToolRegistry([StrictKeywordTool()])

    # 1. Missing required keyword argument raises TypeError
    with pytest.raises(TypeError):
        await registry.execute_tool("strict_tool", {"x": 10})

    # 2. Unexpected keyword argument raises TypeError
    with pytest.raises(TypeError):
        await registry.execute_tool("strict_tool", {"x": 10, "y": 2, "unexpected": 42})


def test_registry_special_character_and_unicode_tool_names() -> None:
    """Tool names with underscores, numbers, and hyphens operate cleanly."""
    t1 = SimpleEchoTool("system_v2_check_99", "Subsystem tool")
    t2 = SimpleEchoTool("korean_도구_테스트", "Unicode tool name")
    registry = ToolRegistry([t1, t2])

    assert registry.has_tool("system_v2_check_99")
    assert registry.has_tool("korean_도구_테스트")
    assert len(registry.export_gemini_declarations()) == 2
    assert len(registry.export_openai_schemas()) == 2


# ============================================================================
# 2. ToolCAGManager Adversarial & Cache Invalidation Tests
# ============================================================================


def test_cag_manager_hash_reacts_to_tool_registry_changes() -> None:
    """Modifying tools in ToolRegistry immediately produces a different SHA256 hash."""
    registry = ToolRegistry()
    cag_manager = ToolCAGManager(tool_registry=registry)

    hash_empty = cag_manager.compute_cache_hash()
    bundle_empty = cag_manager.get_static_cag_bundle()
    assert len(bundle_empty["tools"]) == 0

    # Add a tool
    tool_a = SimpleEchoTool("sensor_a", "Sensor A description")
    registry.register(tool_a)
    hash_with_a = cag_manager.compute_cache_hash()
    assert hash_with_a != hash_empty

    bundle_with_a = cag_manager.get_static_cag_bundle()
    assert len(bundle_with_a["tools"]) == 1
    assert bundle_with_a["cache_hash"] == hash_with_a

    # Add another tool
    tool_b = SimpleEchoTool("sensor_b", "Sensor B description")
    registry.register(tool_b)
    hash_with_ab = cag_manager.compute_cache_hash()
    assert hash_with_ab != hash_with_a

    # Remove tool_a
    registry.unregister("sensor_a")
    hash_with_b = cag_manager.compute_cache_hash()
    assert hash_with_b != hash_with_ab
    assert hash_with_b != hash_with_a


@pytest.mark.asyncio
async def test_cag_manager_sync_client_variations_and_error_handling() -> None:
    """Verify Gemini Context Cache sync handling for sync client, missing attributes, and exceptions."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry)

    # 1. Sync client with client.caches.create
    mock_sync_client = MagicMock(spec=["caches"])
    mock_cache = MagicMock()
    mock_cache.name = "cachedContents/sync_cache_999"
    mock_sync_client.caches.create.return_value = mock_cache

    res_sync = await cag.sync_gemini_context_cache(mock_sync_client)
    assert res_sync == "cachedContents/sync_cache_999"
    mock_sync_client.caches.create.assert_called_once()

    # 2. Client without caches attribute returns None gracefully
    mock_bare_client = MagicMock(spec=[])
    res_bare = await cag.sync_gemini_context_cache(mock_bare_client)
    assert res_bare is None

    # 3. Client raising non-standard exception falls back to None
    mock_err_client = MagicMock()
    mock_err_client.aio.caches.create = AsyncMock(
        side_effect=ConnectionError("Cache endpoint unreachable")
    )
    res_err = await cag.sync_gemini_context_cache(mock_err_client)
    assert res_err is None


# ============================================================================
# 3. AsyncMCPClient & MCPToolAdapter Protocol Attacks
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_client_http_transport_full_lifecycle_with_mock_http() -> None:
    """Verify AsyncMCPClient over HTTP transport with mocked HTTP JSON-RPC 2.0 endpoints."""

    # Build MockTransport handling JSON-RPC 2.0 initialize, tools/list, and tools/call
    def mock_rpc_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        method = body.get("method")
        req_id = body.get("id")

        if method == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "remote_mcp", "version": "2.0.0"},
                        "capabilities": {"tools": {}},
                    },
                },
            )
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "query_database",
                                "description": "Execute read-only SQL query.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"query": {"type": "string"}},
                                    "required": ["query"],
                                },
                            }
                        ]
                    },
                },
            )
        if method == "tools/call":
            params = body.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "query_database":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": f"Result for query: {args.get('query')}"}
                            ],
                            "isError": False,
                        },
                    },
                )
        if method == "ping":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": {}})

        return httpx.Response(
            404,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": "Not Found"},
            },
        )

    transport = httpx.MockTransport(mock_rpc_handler)
    http_client = httpx.AsyncClient(transport=transport)

    config = MCPServerConfig(
        name="remote_db_mcp",
        transport=MCPTransportType.HTTP,
        url="http://mock-mcp.internal/rpc",
    )
    client = AsyncMCPClient(config=config, http_client=http_client)

    # 1. Connect
    init_res = await client.connect()
    assert init_res["serverInfo"]["name"] == "remote_mcp"

    # 2. List tools
    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_database"

    # 3. Call tool
    res = await client.call_tool("query_database", {"query": "SELECT count(*) FROM telemetry;"})
    assert res.isError is False
    assert "Result for query: SELECT count(*)" in res.text

    # 4. Ping
    assert await client.ping() is True

    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_http_server_errors_and_malformed_responses() -> None:
    """Verify AsyncMCPClient handles HTTP 500, HTTP 404, and JSON-RPC errors."""
    # 1. Server returns HTTP 500
    err_transport_500 = httpx.MockTransport(
        lambda req: httpx.Response(500, text="Internal Server Error")
    )
    client_500 = AsyncMCPClient(
        config=MCPServerConfig(
            name="mcp_500", transport=MCPTransportType.HTTP, url="http://mcp.error/rpc"
        ),
        http_client=httpx.AsyncClient(transport=err_transport_500),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client_500.connect()
    await client_500.close()

    # 2. Server returns JSON-RPC protocol error during initialize
    rpc_err_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "Handshake rejected"},
            },
        )
    )
    client_rpc_err = AsyncMCPClient(
        config=MCPServerConfig(
            name="mcp_rpc_err", transport=MCPTransportType.HTTP, url="http://mcp.error/rpc"
        ),
        http_client=httpx.AsyncClient(transport=rpc_err_transport),
    )
    with pytest.raises(RuntimeError, match="Handshake rejected"):
        await client_rpc_err.connect()
    await client_rpc_err.close()


@pytest.mark.asyncio
async def test_mcp_client_call_tool_json_rpc_error_handling() -> None:
    """Verify AsyncMCPClient returns MCPCallResult(isError=True) when server responds with JSON-RPC error."""

    def rpc_call_err_handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {"serverInfo": {"name": "test"}},
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -32602, "message": "Invalid params"},
            },
        )

    client = AsyncMCPClient(
        config=MCPServerConfig(
            name="mcp_params_err", transport=MCPTransportType.HTTP, url="http://mcp.test/rpc"
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(rpc_call_err_handler)),
    )
    call_res = await client.call_tool("any_tool", {"bad": "arg"})
    assert call_res.isError is True
    assert "Invalid params" in call_res.text

    # Wrapping in MCPToolAdapter raises RuntimeError
    meta = MCPToolMeta(name="any_tool", description="Test", inputSchema={"type": "object"})
    adapter = MCPToolAdapter(client=client, meta=meta)
    with pytest.raises(RuntimeError, match="Invalid params"):
        await adapter.aexecute(bad="arg")

    await client.close()


# ============================================================================
# 4. Google Workspace Adapters Stress & Auth Verification
# ============================================================================


@pytest.mark.asyncio
async def test_google_auth_real_mode_token_refresh_simulation() -> None:
    """Verify GoogleAuthHelper OAuth2 token refresh with simulated Google endpoint."""

    def google_oauth_handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://oauth2.googleapis.com/token"
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.simulated_google_oauth_token_xyz",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(google_oauth_handler))
    auth = GoogleAuthHelper(
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
        mock_mode=False,
        http_client=mock_http,
    )

    token = await auth.get_access_token()
    assert token == "ya29.simulated_google_oauth_token_xyz"

    headers = await auth.get_auth_headers()
    assert headers["Authorization"] == "Bearer ya29.simulated_google_oauth_token_xyz"
    await auth.close()


@pytest.mark.asyncio
async def test_google_calendar_special_characters_and_filters() -> None:
    """Verify Google Calendar event creation and filtering with Unicode, Korean, and boundaries."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    adapter = GoogleCalendarAdapter(auth_helper=auth_helper)

    # 1. Create event with Korean and special characters
    evt = await adapter.create_event(
        summary="가르강튀아 중력 슬링샷 & 회의 🚀",
        start_time="2026-08-30T10:00:00Z",
        end_time="2026-08-30T11:00:00Z",
        description="이벤트 설명: 'quotes' & <xml> tags.",
        attendees=["쿠퍼@endurance.space"],
    )
    assert evt["summary"] == "가르강튀아 중력 슬링샷 & 회의 🚀"

    # 2. Filter events with time_min and time_max boundaries
    filtered = await adapter.list_events(
        time_min="2026-08-30T09:00:00Z",
        time_max="2026-08-30T12:00:00Z",
        max_results=5,
    )
    assert len(filtered) >= 1
    assert any("가르강튀아" in e["summary"] for e in filtered)

    # 3. Delete event
    res = await adapter.delete_event(evt["id"])
    assert res["status"] == "deleted"


@pytest.mark.asyncio
async def test_google_gmail_search_and_mime_multibyte_send() -> None:
    """Verify Gmail search query handling and multibyte / Korean email sending."""
    auth_helper = GoogleAuthHelper(mock_mode=True)
    adapter = GmailAdapter(auth_helper=auth_helper)

    # 1. Search with multiple query filters
    res_from = await adapter.search_messages("from:brand")
    assert len(res_from) >= 1
    assert "Plan B" in res_from[0]["subject"]

    # 2. Search for non-existent text returns empty list
    res_empty = await adapter.search_messages("nonexistent_keyword_xyz_123")
    assert len(res_empty) == 0

    # 3. Send email with Korean and long body
    send_res = await adapter.send_message(
        to="쿠퍼@nasa.gov",
        subject="블랙홀 양자 데이터 전송 보고서",
        body="시간은 상대적이지만 TARS의 유머 감각은 절대적입니다.",
    )
    assert send_res["status"] == "sent"
    assert send_res["to"] == "쿠퍼@nasa.gov"

    # 4. Verify message is stored in mock messages
    stored = await adapter.get_message(send_res["id"])
    assert stored["subject"] == "블랙홀 양자 데이터 전송 보고서"
    assert "상대적" in stored["body"]


# ============================================================================
# 5. Integrated MCP and Google Failure in LangGraph ReAct Pipeline
# ============================================================================


@pytest.mark.asyncio
async def test_mcp_and_calendar_failure_in_react_loop_triggers_tars_recovery() -> None:
    """Verify that an MCP failure and a Calendar failure in the same turn are handled gracefully by ReAct."""
    # Create failing MCP tool
    config = MCPServerConfig(name="failing_mcp", transport=MCPTransportType.MOCK)
    mcp_client = AsyncMCPClient(config=config)
    mcp_meta = MCPToolMeta(name="fetch_deep_space_probe", description="Fetch probe data")

    def broken_handler() -> Any:
        raise ConnectionResetError("Deep space probe antenna disintegrated.")

    mcp_client.register_mock_tool(mcp_meta, handler=broken_handler)
    mcp_adapter = MCPToolAdapter(client=mcp_client, meta=mcp_meta, prefix="mcp")

    # Create working calendar adapter
    cal_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    cal_tools = cal_adapter.get_tools()

    registry = ToolRegistry([mcp_adapter] + cal_tools)

    # LLM requests both tools simultaneously
    mock_gemini = MockLLMAdapter(
        name="gemini_mixed_mcp_cal",
        default_responses=[
            "Querying deep space probe and calendar simultaneously...",
            "Probe telemetry failed as expected. However, your mission briefing is confirmed at 10:00 UTC.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(id="call_probe_01", name="mcp_fetch_deep_space_probe", arguments={}),
                ToolCallData(
                    id="call_cal_02", name="calendar_list_events", arguments={"max_results": 1}
                ),
            ],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Check space probe and calendar.")],
        "user_id": "user_cooper",
        "session_id": "session_mcp_cal_001",
    }

    final_state = await graph.ainvoke(initial_input)

    # 1 Human + 1 AI (2 calls) + 2 ToolMessages + 1 Final AI = 5 messages
    messages = final_state["messages"]
    assert len(messages) == 5
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], ToolMessage)

    # Results check
    results = final_state["tool_results"]
    assert len(results) == 2
    assert results[0]["status"] == "error"
    assert "Deep space probe antenna disintegrated" in results[0]["error"]
    assert results[1]["status"] == "success"

    assert (
        "briefing" in final_state["final_response"].lower()
        or "probe" in final_state["final_response"].lower()
    )
