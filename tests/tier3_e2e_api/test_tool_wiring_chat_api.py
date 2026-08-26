"""Tier 3 E2E API Tests: ToolRegistry Dependency Injection and Chat API Wiring.

Verifies:
1. get_tool_registry dependency returns a valid ToolRegistry with default Google tools.
2. chat_sse_stream endpoint receives ToolRegistry and passes declarations to LLM router.
3. Custom MCP tools can be injected into FastAPI via dependency_overrides.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tars.adapters.router import HybridLLMRouter
from tars.api.dependencies import get_tool_registry
from tars.db.models import User
from tars.tools.base import BaseTool
from tars.tools.registry import ToolRegistry


class DummyEchoTool(BaseTool):
    """Simple test tool for dependency injection verification."""

    def __init__(self) -> None:
        super().__init__(
            name="dummy_echo_tool",
            description="Echo back input message for testing.",
            parameters_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> str:
        return f"Echo: {kwargs.get('message', '')}"


@pytest.mark.asyncio
async def test_get_tool_registry_default_tools() -> None:
    """Verify get_tool_registry provides default Google Calendar and Gmail tools."""
    registry = await get_tool_registry()
    assert isinstance(registry, ToolRegistry)
    tool_names = registry.list_tool_names()
    assert "calendar_list_events" in tool_names
    assert "calendar_create_event" in tool_names
    assert "calendar_delete_event" in tool_names
    assert "gmail_list_messages" in tool_names
    assert "gmail_send_message" in tool_names


@pytest.mark.asyncio
async def test_chat_sse_stream_receives_tool_registry(
    authenticated_client: AsyncClient,
    test_user: User,
) -> None:
    """Verify chat_sse_stream successfully receives ToolRegistry and passes tools to router."""
    received_tools: list[dict[str, Any]] | None = None

    async def mock_route_and_stream(messages: Any, system_prompt: str = "", **kwargs: Any) -> Any:
        nonlocal received_tools
        received_tools = kwargs.get("tools")
        yield "Testing "
        yield "tool "
        yield "wiring!"

    with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_route_and_stream):
        response = await authenticated_client.post(
            "/api/v1/chat/stream",
            json={"message": "오늘 일정 어때?", "session_id": "test_tool_session"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert received_tools is not None
        tool_names = [t["name"] for t in received_tools]
        assert "calendar_list_events" in tool_names


@pytest.mark.asyncio
async def test_custom_mcp_tool_injection_via_dependency_override(
    app: Any,
    authenticated_client: AsyncClient,
) -> None:
    """Verify custom MCP tools can be injected into FastAPI via dependency_overrides."""
    custom_registry = ToolRegistry([DummyEchoTool()])

    app.dependency_overrides[get_tool_registry] = lambda: custom_registry

    try:
        received_tools: list[dict[str, Any]] | None = None

        async def mock_route_and_stream(messages: Any, system_prompt: str = "", **kwargs: Any) -> Any:
            nonlocal received_tools
            received_tools = kwargs.get("tools")
            yield "Custom tool injected!"

        with patch.object(HybridLLMRouter, "route_and_stream", side_effect=mock_route_and_stream):
            response = await authenticated_client.post(
                "/api/v1/chat/stream",
                json={"message": "Echo test", "session_id": "test_echo_session"},
            )

            assert response.status_code == 200
            assert received_tools is not None
            assert len(received_tools) == 1
            assert received_tools[0]["name"] == "dummy_echo_tool"
    finally:
        app.dependency_overrides.pop(get_tool_registry, None)
