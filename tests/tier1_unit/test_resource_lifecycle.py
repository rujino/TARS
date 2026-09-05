"""Tier 1 Unit Tests: Resource & Connection Lifecycle Management (RES-01, RES-02).

Verifies:
1. ToolRegistry tracking of underlying clients and adapters.
2. ToolRegistry.aclose() and close() methods gracefully closing tracked clients and clearing state.
3. get_tool_registry() singleton memoization.
4. close_tool_registry() cleans up singleton and resets global reference to None.
5. Direct aclose()/close() on LlamaCppAdapter, GoogleCalendarAdapter, GmailAdapter, and AsyncMCPClient.
6. FastAPI lifespan context manager invoking both close_tool_registry() and close_db() on shutdown.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from langchain_core.tools import tool

from tars.adapters.llamacpp import LlamaCppAdapter
from tars.api.app import lifespan
from tars.api.dependencies import close_tool_registry, get_tool_registry
from tars.tools.google.calendar import GoogleCalendarAdapter
from tars.tools.google.gmail import GmailAdapter
from tars.tools.mcp.client import AsyncMCPClient
from tars.tools.mcp.models import MCPServerConfig
from tars.tools.registry import ToolRegistry


@tool
def sample_test_tool(x: int) -> int:
    """A sample tool for testing registry."""
    return x * 2


@pytest.mark.asyncio
async def test_tool_registry_track_client_and_aclose() -> None:
    """Verify ToolRegistry tracks clients and closes them via aclose()."""
    registry = ToolRegistry()
    registry.register(sample_test_tool)
    assert "sample_test_tool" in registry.list_tool_names()

    # Mock clients with aclose and close
    mock_async_client = AsyncMock()
    mock_sync_client = MagicMock(spec=["close"])

    registry.track_client(mock_async_client)
    registry.track_client(mock_sync_client)

    assert len(registry._managed_clients) == 2

    # Avoid duplicate tracking
    registry.track_client(mock_async_client)
    assert len(registry._managed_clients) == 2

    await registry.aclose()

    mock_async_client.aclose.assert_awaited_once()
    mock_sync_client.close.assert_called_once()
    assert len(registry._managed_clients) == 0
    assert len(registry._tools) == 0
    assert "sample_test_tool" not in registry.list_tool_names()


@pytest.mark.asyncio
async def test_get_tool_registry_singleton_caching() -> None:
    """Verify get_tool_registry() memoizes the singleton instance across repeated calls."""
    try:
        await close_tool_registry()

        r1 = await get_tool_registry()
        r2 = await get_tool_registry()

        assert r1 is r2, "get_tool_registry must return the memoized singleton instance"
        assert isinstance(r1, ToolRegistry)
    finally:
        await close_tool_registry()


@pytest.mark.asyncio
async def test_close_tool_registry_resets_singleton() -> None:
    """Verify close_tool_registry() calls aclose and resets singleton to None."""
    try:
        r1 = await get_tool_registry()
        assert r1 is not None

        with patch.object(r1, "aclose", new_callable=AsyncMock) as mock_aclose:
            await close_tool_registry()
            mock_aclose.assert_awaited_once()

        # Next call should create a brand new registry
        r2 = await get_tool_registry()
        assert r2 is not r1
    finally:
        await close_tool_registry()


@pytest.mark.asyncio
async def test_adapter_aclose_methods() -> None:
    """Verify aclose/close methods on individual client adapters."""
    # 1. LlamaCppAdapter
    llamacpp = LlamaCppAdapter()
    client = llamacpp._get_http_client()
    assert client is not None
    assert not client.is_closed
    await llamacpp.aclose()
    assert client.is_closed
    assert llamacpp._client is None

    # 2. GoogleCalendarAdapter
    cal_adapter = GoogleCalendarAdapter()
    with patch.object(cal_adapter.auth_helper, "close", new_callable=AsyncMock) as mock_auth_close:
        await cal_adapter.aclose()
        mock_auth_close.assert_awaited_once()

    # 3. GmailAdapter
    gmail_adapter = GmailAdapter()
    with patch.object(gmail_adapter.auth_helper, "close", new_callable=AsyncMock) as mock_auth_close:
        await gmail_adapter.aclose()
        mock_auth_close.assert_awaited_once()

    # 4. AsyncMCPClient
    mcp_client = AsyncMCPClient(config=MCPServerConfig(name="test_mcp", url="http://localhost:9999/sse"))
    with patch.object(mcp_client, "close", new_callable=AsyncMock) as mock_mcp_close:
        await mcp_client.aclose()
        mock_mcp_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fastapi_lifespan_disposes_database_and_tool_registry() -> None:
    """Verify FastAPI application lifespan executes close_tool_registry and close_db upon shutdown."""
    app = FastAPI(lifespan=lifespan)
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    with patch("tars.api.app.get_engine", return_value=mock_engine):
        with patch("tars.api.app.close_tool_registry", new_callable=AsyncMock) as mock_close_tools:
            with patch("tars.api.app.close_db", new_callable=AsyncMock) as mock_close_db:
                with patch("tars.api.app.shutdown_background_tasks", new_callable=AsyncMock) as mock_drain:
                    async with lifespan(app):
                        assert hasattr(app.state, "tool_registry")
                        assert app.state.tool_registry is not None

                    mock_drain.assert_awaited_once_with(timeout=5.0)
                    mock_close_tools.assert_awaited_once()
                    mock_close_db.assert_awaited_once()
