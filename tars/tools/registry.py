"""Central Tool Registry for registering, discovering, and executing TARS tools.

Supports:
- Dynamic tool registration and unregistration
- Schema export for Gemini and OpenAI / LangGraph adapters
- Thread-safe / async execution routing
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from tars.tools.base import BaseTool

logger = logging.getLogger("tars.tools.registry")


class ToolRegistry:
    """Registry maintaining all tools available to the TARS agent."""

    def __init__(self, tools: Sequence[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

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

    def export_gemini_declarations(self) -> list[dict[str, Any]]:
        """Export all tool declarations in Google Gemini function calling format."""
        return [tool.to_gemini_declaration() for tool in self._tools.values()]

    def export_openai_schemas(self) -> list[dict[str, Any]]:
        """Export all tool schemas in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def export_schemas(self) -> list[dict[str, Any]]:
        """Default schema export (Gemini FunctionDeclaration format)."""
        return self.export_gemini_declarations()

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a registered tool by name asynchronously.

        Args:
            name: Name of the tool to execute.
            arguments: Dictionary of arguments passed to tool.

        Returns:
            Result of tool execution.

        Raises:
            KeyError: If tool is not registered.
            Exception: Any exception raised by tool execution.
        """
        tool = self.get_tool(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' is not registered in ToolRegistry.")

        logger.info("Executing tool '%s' with arguments: %s", name, arguments)
        return await tool.aexecute(**arguments)

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
