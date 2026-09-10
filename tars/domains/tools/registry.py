"""Central Tool Registry for registering, discovering, and executing TARS tools.

Supports:
- Dynamic tool registration and unregistration
- Schema export for Gemini and OpenAI / LangGraph adapters
- Thread-safe / async execution routing
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from tars.domains.tools.base import BaseTool

logger = logging.getLogger("tars.domains.tools.registry")


class ToolRegistry:
    """Registry maintaining all tools available to the TARS agent."""

    def __init__(self, tools: Sequence[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._managed_clients: list[Any] = []
        if tools:
            for tool in tools:
                self.register(tool)

    def track_client(self, client: Any) -> None:
        """Track an underlying client or adapter resource for lifecycle cleanup."""
        if client not in self._managed_clients:
            self._managed_clients.append(client)

    def invalidate_user_google_cache(self, user_id: str) -> None:
        """Evict cached Google tokens for a specific user across managed adapters."""
        for client in self._managed_clients:
            auth_helper = getattr(client, "auth_helper", None)
            if auth_helper and hasattr(auth_helper, "invalidate_user_cache"):
                auth_helper.invalidate_user_cache(user_id)

    async def aclose(self) -> None:
        """Gracefully close all managed HTTP clients and connections."""
        for client in list(self._managed_clients):
            try:
                if hasattr(client, "aclose") and callable(client.aclose):
                    res = client.aclose()
                    if asyncio.iscoroutine(res):
                        await res
                elif hasattr(client, "close") and callable(client.close):
                    res = client.close()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as exc:
                logger.warning("Error closing managed client %r: %s", client, exc)
        self._managed_clients.clear()
        self._tools.clear()

    async def close(self) -> None:
        """Alias for aclose."""
        await self.aclose()

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance in the registry.

        Args:
            tool: BaseTool instance to register.
        """
        if not tool.name:
            raise ValueError("Cannot register tool without a valid name.")
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (%s)", tool.name, tool.description)

    def register_many(self, tools: Sequence[BaseTool]) -> None:
        """Register multiple tools at once.

        Args:
            tools: Sequence of BaseTool instances.
        """
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name.

        Args:
            name: Name of the tool to unregister.

        Returns:
            bool: True if removed, False if tool was not found.
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug("Unregistered tool: %s", name)
            return True
        return False

    def get_tool(self, name: str) -> BaseTool | None:
        """Retrieve a registered tool by name.

        Args:
            name: Unique name of the tool.

        Returns:
            BaseTool instance or None if not found.
        """
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered.

        Args:
            name: Unique name of the tool.

        Returns:
            bool: True if registered, False otherwise.
        """
        return name in self._tools

    def list_tools(self) -> list[BaseTool]:
        """Return all currently registered tool instances."""
        return list(self._tools.values())

    def list_tool_names(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self._tools.keys())

    def export_gemini_declarations(
        self, disabled_tools: Sequence[str] | set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Export all tool declarations in Google Gemini function calling format.

        Args:
            disabled_tools: Optional sequence or set of tool names to exclude.

        Returns:
            List of Gemini FunctionDeclaration dictionaries for active tools.
        """
        disabled = set(disabled_tools) if disabled_tools else set()
        return [
            tool.to_gemini_declaration()
            for name, tool in self._tools.items()
            if name not in disabled
        ]

    def export_openai_schemas(
        self, disabled_tools: Sequence[str] | set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Export all tool schemas in OpenAI function calling format.

        Args:
            disabled_tools: Optional sequence or set of tool names to exclude.

        Returns:
            List of OpenAI function schema dictionaries for active tools.
        """
        disabled = set(disabled_tools) if disabled_tools else set()
        return [
            tool.to_openai_schema() for name, tool in self._tools.items() if name not in disabled
        ]

    def export_schemas(
        self, disabled_tools: Sequence[str] | set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Default schema export (Gemini FunctionDeclaration format)."""
        return self.export_gemini_declarations(disabled_tools=disabled_tools)

    async def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        user_id: str | None = None,
    ) -> Any:
        """Execute a registered tool by name asynchronously.

        Args:
            name: Name of the tool to execute.
            arguments: Dictionary of arguments passed to tool.
            user_id: Optional user ID for multi-tenant context and authentication.

        Returns:
            Result of tool execution.

        Raises:
            KeyError: If tool is not registered.
            Exception: Any exception raised by tool execution.
        """
        tool = self.get_tool(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' is not registered in ToolRegistry.")

        logger.info(
            "Executing tool '%s' with arguments: %s (user_id: %s)",
            name,
            arguments,
            user_id,
        )
        import inspect

        sig = inspect.signature(tool.aexecute)
        call_kwargs = dict(arguments)
        if "user_id" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            call_kwargs["user_id"] = user_id

        return await tool.aexecute(**call_kwargs)

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


__all__ = [
    "ToolRegistry",
]
