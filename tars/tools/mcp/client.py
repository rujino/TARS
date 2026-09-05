"""Asynchronous Model Context Protocol (MCP) Client based on JSON-RPC 2.0.

Supports:
- SSE / HTTP REST transports via httpx
- Deterministic Mock transport for unit/integration testing
- Full lifecycle: initialize, tools/list, tools/call, ping, and close
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx

from tars.tools.mcp.models import (
    MCPCallResult,
    MCPServerConfig,
    MCPToolMeta,
    MCPTransportType,
)

logger = logging.getLogger("tars.tools.mcp.client")


class AsyncMCPClient:
    """Asynchronous client communicating with an MCP server via JSON-RPC 2.0."""

    def __init__(
        self,
        config: MCPServerConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._is_connected = False
        self._request_id = 0
        self._server_info: dict[str, Any] = {}
        # In-memory mock tools registry for mock transport
        self._mock_tools: dict[str, MCPToolMeta] = {}
        self._mock_handlers: dict[str, Callable[..., Any]] = {}

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._http_client

    def register_mock_tool(
        self,
        tool_meta: MCPToolMeta,
        handler: Callable[..., Any] | None = None,
    ) -> None:
        """Register a mock tool and optional execution handler for testing."""
        self._mock_tools[tool_meta.name] = tool_meta
        if handler:
            self._mock_handlers[tool_meta.name] = handler

    async def connect(self) -> dict[str, Any]:
        """Establish connection and execute initialize handshake with the MCP server."""
        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "TARS", "version": "1.0.0"},
            },
        }

        if self.config.transport == MCPTransportType.MOCK:
            self._is_connected = True
            self._server_info = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": self.config.name, "version": "1.0.0-mock"},
                "capabilities": {"tools": {"listChanged": False}},
            }
            logger.info("Connected to Mock MCP server: %s", self.config.name)
            return self._server_info

        if not self.config.url:
            raise ValueError(
                f"MCP server '{self.config.name}' requires a URL for {self.config.transport} transport."
            )

        client = self._get_http_client()
        resp = await client.post(self.config.url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"MCP initialize error: {data['error']}")

        self._is_connected = True
        self._server_info = data.get("result", {})
        logger.info("Connected to MCP server: %s (%s)", self.config.name, self.config.url)
        return self._server_info

    async def initialize(self) -> dict[str, Any]:
        """Alias for connect()."""
        return await self.connect()

    async def list_tools(self) -> list[MCPToolMeta]:
        """Query available tools from the MCP server (tools/list)."""
        if not self._is_connected:
            await self.connect()

        if self.config.transport == MCPTransportType.MOCK:
            return list(self._mock_tools.values())

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/list",
            "params": {},
        }

        if not self.config.url:
            raise ValueError(f"MCP server '{self.config.name}' requires a valid URL.")

        client = self._get_http_client()
        resp = await client.post(self.config.url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise RuntimeError(f"MCP tools/list error: {data['error']}")

        tools_data = data.get("result", {}).get("tools", [])
        tools: list[MCPToolMeta] = []
        for t in tools_data:
            tools.append(
                MCPToolMeta(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
                )
            )
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> MCPCallResult:
        """Invoke a tool on the remote MCP server with retry backoff and timeout guard."""
        if not self._is_connected:
            await self.connect()

        effective_timeout = timeout if timeout is not None else (self.config.timeout or 10.0)

        try:
            return await asyncio.wait_for(
                self._execute_tool_with_retry(name, arguments),
                timeout=effective_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("MCP tool '%s' timed out after %.1fs", name, effective_timeout)
            return MCPCallResult(
                content=[
                    {
                        "type": "text",
                        "text": f"Execution timed out after {effective_timeout}s",
                    }
                ],
                isError=True,
            )

    async def _execute_tool_with_retry(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPCallResult:
        args = arguments or {}
        if self.config.transport == MCPTransportType.MOCK:
            if name not in self._mock_tools:
                return MCPCallResult(
                    content=[
                        {"type": "text", "text": f"Error: Tool '{name}' not found on mock server."}
                    ],
                    isError=True,
                )
            handler = self._mock_handlers.get(name)
            if handler is not None:
                try:
                    import inspect

                    if inspect.iscoroutinefunction(handler):
                        res = await handler(**args)
                    else:
                        res = handler(**args)

                    if isinstance(res, MCPCallResult):
                        return res
                    if isinstance(res, str):
                        return MCPCallResult(content=[{"type": "text", "text": res}], isError=False)
                    return MCPCallResult(
                        content=[{"type": "text", "text": str(res)}],
                        isError=False,
                        structured_data=res if isinstance(res, (dict, list)) else None,
                    )
                except Exception as exc:
                    return MCPCallResult(
                        content=[{"type": "text", "text": f"Execution error in {name}: {exc}"}],
                        isError=True,
                    )
            return MCPCallResult(
                content=[{"type": "text", "text": f"Mock executed {name} with args: {args}"}],
                isError=False,
                structured_data={"status": "mock_success", "tool": name, "arguments": args},
            )

        req_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }

        if not self.config.url:
            raise ValueError(f"MCP server '{self.config.name}' requires a valid URL.")

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                client = self._get_http_client()
                resp = await client.post(self.config.url, json=payload)
                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    err_msg = (
                        data["error"].get("message", str(data["error"]))
                        if isinstance(data["error"], dict)
                        else str(data["error"])
                    )
                    return MCPCallResult(
                        content=[{"type": "text", "text": f"MCP tool error: {err_msg}"}],
                        isError=True,
                    )

                result_data = data.get("result", {})
                content = result_data.get("content", [])
                is_error = result_data.get("isError", False)
                return MCPCallResult(content=content, isError=is_error)

            except (httpx.ConnectError, httpx.HTTPStatusError) as exc:
                is_retryable = isinstance(exc, httpx.ConnectError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in (502, 503, 504)
                )
                if not is_retryable or attempt == max_retries:
                    logger.error(
                        "MCP tool '%s' failed (attempt %d/%d): %s",
                        name,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    return MCPCallResult(
                        content=[{"type": "text", "text": f"MCP tool network failure: {exc}"}],
                        isError=True,
                    )
                delay = 0.5 * (2**attempt)
                logger.warning(
                    "MCP tool '%s' transient failure (%s); retrying in %.2fs...",
                    name,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                logger.error("MCP tool '%s' unexpected failure: %s", name, exc, exc_info=True)
                return MCPCallResult(
                    content=[{"type": "text", "text": f"MCP tool unexpected error: {exc}"}],
                    isError=True,
                )

        return MCPCallResult(
            content=[{"type": "text", "text": f"MCP tool '{name}' failed after retries"}],
            isError=True,
        )

    async def ping(self) -> bool:
        """Check if MCP server connection is healthy."""
        try:
            if self.config.transport == MCPTransportType.MOCK:
                return self._is_connected
            if not self.config.url:
                return False
            client = self._get_http_client()
            req_id = self._next_id()
            resp = await client.post(
                self.config.url,
                json={"jsonrpc": "2.0", "id": req_id, "method": "ping", "params": {}},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close client resources."""
        self._is_connected = False
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def aclose(self) -> None:
        """Alias for close."""
        await self.close()


__all__ = [
    "AsyncMCPClient",
]
