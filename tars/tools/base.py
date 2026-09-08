"""Abstract Base Tool interface and schema models for TARS tool system.

Provides:
- ToolParameter: Pydantic model for parameter specifications.
- ToolDefinition: Pydantic model for tool metadata and schemas.
- BaseTool: Abstract base class for all internal, Google, and MCP tools.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def coerce_json_str_to_list(v: Any) -> Any:
    """Coerce a JSON-encoded string to a list if passed as string by an LLM client."""
    if not isinstance(v, str):
        return v
    try:
        parsed = json.loads(v)
        return parsed if isinstance(parsed, list) else v
    except (json.JSONDecodeError, TypeError):
        return v


def coerce_json_str_to_dict(v: Any) -> Any:
    """Coerce a JSON-encoded string to a dict if passed as string by an LLM client."""
    if not isinstance(v, str):
        return v
    try:
        parsed = json.loads(v)
        return parsed if isinstance(parsed, dict) else v
    except (json.JSONDecodeError, TypeError):
        return v


def coerce_to_string_list(v: Any) -> list[str]:
    """Coerce input (list, JSON array string, comma-separated string, or single string) to list[str].

    Handles cases where LLMs provide:
    - Native list: ['a', 'b']
    - JSON-encoded list: '["a", "b"]'
    - Comma-separated string: 'a, b'
    - Single string: 'a'
    - None or empty values: returns []
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(item).strip() for item in v if str(item).strip()]
    if isinstance(v, str):
        cleaned = v.strip()
        if not cleaned:
            return []
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        if "," in cleaned:
            return [part.strip() for part in cleaned.split(",") if part.strip()]
        return [cleaned]
    return [str(v).strip()] if str(v).strip() else []


StringList = Annotated[list[str], BeforeValidator(coerce_json_str_to_list)]
DictList = Annotated[list[dict[str, Any]], BeforeValidator(coerce_json_str_to_list)]
JsonDict = Annotated[dict[str, Any], BeforeValidator(coerce_json_str_to_dict)]


class ToolParameter(BaseModel):
    """Specification of an individual tool parameter."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Parameter name")
    type: str = Field(
        default="string",
        description="JSON Schema type (string, integer, boolean, object, array, number)",
    )
    description: str = Field(default="", description="Description of the parameter")
    required: bool = Field(default=True, description="Whether parameter is mandatory")
    default: Any = Field(default=None, description="Default value if not provided")
    enum: list[str] | None = Field(default=None, description="Allowed string values")
    items: dict[str, Any] | None = Field(
        default=None, description="Array element schema if type is array"
    )


class ToolDefinition(BaseModel):
    """Metadata and schema specification for a tool."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Unique tool name")
    description: str = Field(default="", description="Functional description of the tool")
    parameters_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
        description="JSON Schema object describing input parameters",
    )


class BaseTool(ABC):
    """Abstract base class unifying all tools available to the TARS agent."""

    name: str
    description: str
    parameters_schema: dict[str, Any]

    def __init__(
        self,
        name: str | None = None,
        description: str | None = None,
        parameters_schema: dict[str, Any] | None = None,
    ) -> None:
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if parameters_schema is not None:
            self.parameters_schema = parameters_schema
        elif not hasattr(self, "parameters_schema"):
            self.parameters_schema = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def aexecute(self, *, user_id: str | None = None, **kwargs: Any) -> Any:
        """Execute the tool asynchronously with supplied arguments.

        Args:
            user_id: Optional authenticated user ID executing the tool (for multi-tenant isolation).
            **kwargs: Arguments matching parameters_schema.

        Returns:
            Tool execution result (dict, str, list, etc.).
        """

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Export as Gemini FunctionDeclaration schema dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

    def to_openai_schema(self) -> dict[str, Any]:
        """Export as OpenAI Function Calling schema dictionary."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def to_definition(self) -> ToolDefinition:
        """Export as ToolDefinition Pydantic model."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters_schema=self.parameters_schema,
        )


__all__ = [
    "BaseTool",
    "DictList",
    "JsonDict",
    "StringList",
    "ToolDefinition",
    "ToolParameter",
    "coerce_json_str_to_dict",
    "coerce_json_str_to_list",
    "coerce_to_string_list",
]
