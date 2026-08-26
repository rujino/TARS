"""Tier 1 Unit Tests: Tool Abstraction, ToolRegistry, and ToolCAGManager.

Tests:
1. BaseTool, ToolParameter, and ToolDefinition validation and schema exports.
2. ToolRegistry registration, unregistration, discovery, schema translation, and async execution.
3. ToolCAGManager static bundle creation, hash computation, Gemini cache sync, and in-memory fallback.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tars.tools.base import BaseTool, ToolDefinition, ToolParameter
from tars.tools.cag import ToolCAGManager
from tars.tools.registry import ToolRegistry


class DummyCalculatorTool(BaseTool):
    """Test tool that adds two numbers."""

    def __init__(self) -> None:
        super().__init__(
            name="calculator_add",
            description="Add two numbers together.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> float:
        a = float(kwargs.get("a", 0))
        b = float(kwargs.get("b", 0))
        return a + b


class DummyFailingTool(BaseTool):
    """Test tool that always raises an exception."""

    def __init__(self) -> None:
        super().__init__(
            name="failing_tool",
            description="A tool that fails deliberately.",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        raise ValueError("Simulated sensor malfunction.")


# ============================================================================
# 1. BaseTool & Parameter Tests
# ============================================================================


def test_tool_parameter_and_definition_models() -> None:
    """Verify ToolParameter and ToolDefinition Pydantic models."""
    param = ToolParameter(
        name="query",
        type="string",
        description="Search query",
        required=True,
        default="",
    )
    assert param.name == "query"
    assert param.type == "string"
    assert param.required is True

    tool_def = ToolDefinition(
        name="search_wiki",
        description="Search knowledge base",
        parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    assert tool_def.name == "search_wiki"
    assert "query" in tool_def.parameters_schema["properties"]


def test_base_tool_schema_exports() -> None:
    """Verify Gemini and OpenAI schema exports from BaseTool."""
    tool = DummyCalculatorTool()

    # Gemini declaration format
    gemini_decl = tool.to_gemini_declaration()
    assert gemini_decl["name"] == "calculator_add"
    assert gemini_decl["description"] == "Add two numbers together."
    assert "a" in gemini_decl["parameters"]["properties"]
    assert "b" in gemini_decl["parameters"]["properties"]

    # OpenAI schema format
    openai_schema = tool.to_openai_schema()
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "calculator_add"
    assert openai_schema["function"]["parameters"]["required"] == ["a", "b"]

    # Definition model
    definition = tool.to_definition()
    assert definition.name == "calculator_add"


# ============================================================================
# 2. ToolRegistry Tests
# ============================================================================


@pytest.mark.asyncio
async def test_tool_registry_lifecycle() -> None:
    """Verify registering, retrieving, executing, and unregistering tools."""
    registry = ToolRegistry()
    tool = DummyCalculatorTool()

    assert len(registry) == 0
    assert not registry.has_tool("calculator_add")

    # Register
    registry.register(tool)
    assert len(registry) == 1
    assert registry.has_tool("calculator_add")
    assert "calculator_add" in registry
    assert registry.get_tool("calculator_add") is tool
    assert registry.list_tool_names() == ["calculator_add"]

    # Execute
    result = await registry.execute_tool("calculator_add", {"a": 40, "b": 2})
    assert result == 42.0

    # Unregister
    removed = registry.unregister("calculator_add")
    assert removed is True
    assert len(registry) == 0
    assert not registry.has_tool("calculator_add")

    # Unregister nonexistent
    assert registry.unregister("calculator_add") is False


@pytest.mark.asyncio
async def test_tool_registry_missing_tool_raises_key_error() -> None:
    """Verify executing unregistered tool raises KeyError."""
    registry = ToolRegistry()
    with pytest.raises(KeyError, match="not registered"):
        await registry.execute_tool("nonexistent_tool", {})


@pytest.mark.asyncio
async def test_tool_registry_bulk_operations_and_exports() -> None:
    """Verify register_many, export_gemini_declarations, and clear."""
    calc_tool = DummyCalculatorTool()
    fail_tool = DummyFailingTool()
    registry = ToolRegistry([calc_tool])
    assert len(registry) == 1

    registry.register_many([fail_tool])
    assert len(registry) == 2

    declarations = registry.export_gemini_declarations()
    assert len(declarations) == 2
    names = {d["name"] for d in declarations}
    assert names == {"calculator_add", "failing_tool"}

    openai_schemas = registry.export_openai_schemas()
    assert len(openai_schemas) == 2

    registry.clear()
    assert len(registry) == 0


# ============================================================================
# 3. ToolCAGManager Tests
# ============================================================================


def test_tool_cag_manager_bundle_and_hash_computation() -> None:
    """Verify ToolCAGManager computes deterministic hashes and bundles static context."""
    registry = ToolRegistry([DummyCalculatorTool()])
    cag_manager = ToolCAGManager(tool_registry=registry, ttl_seconds=1800)

    bundle1 = cag_manager.get_static_cag_bundle()
    assert "system_prompt" in bundle1
    assert "TARS" in bundle1["system_prompt"]
    assert len(bundle1["tools"]) == 1
    assert bundle1["tools"][0]["name"] == "calculator_add"
    assert bundle1["ttl_seconds"] == 1800
    assert bundle1["cache_hash"] != ""

    # Calling again returns cached bundle
    bundle2 = cag_manager.get_static_cag_bundle()
    assert bundle1 is bundle2

    # Invalidate and recompute
    cag_manager.invalidate_cache()
    bundle3 = cag_manager.get_static_cag_bundle()
    assert bundle3["cache_hash"] == bundle1["cache_hash"]


@pytest.mark.asyncio
async def test_tool_cag_manager_gemini_context_cache_sync() -> None:
    """Verify Gemini Context Cache sync with async mock client and error fallback."""
    registry = ToolRegistry([DummyCalculatorTool()])
    cag_manager = ToolCAGManager(tool_registry=registry, ttl_seconds=3600)

    # 1. Mock GenAI Client with async caches.create
    mock_cache_obj = MagicMock()
    mock_cache_obj.name = "cachedContents/tars_cag_hash_12345"

    mock_client = MagicMock()
    mock_client.aio.caches.create = AsyncMock(return_value=mock_cache_obj)

    cached_id = await cag_manager.sync_gemini_context_cache(
        client=mock_client,
        model_name="gemini-2.0-flash",
    )
    assert cached_id == "cachedContents/tars_cag_hash_12345"
    mock_client.aio.caches.create.assert_awaited_once()

    # 2. None client returns None without error (fallback)
    cag_manager.invalidate_cache()
    fallback_id = await cag_manager.sync_gemini_context_cache(client=None)
    assert fallback_id is None

    # 3. Client raising exception gracefully falls back to None
    failing_client = MagicMock()
    failing_client.aio.caches.create = AsyncMock(
        side_effect=RuntimeError("Token count below 32768 threshold for Context Caching")
    )
    res = await cag_manager.sync_gemini_context_cache(client=failing_client)
    assert res is None
