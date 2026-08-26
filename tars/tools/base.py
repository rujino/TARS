"""Abstract Base Tool interface and schema models for TARS tool system.

Provides:
- ToolParameter: Pydantic model for parameter specifications.
- ToolDefinition: Pydantic model for tool metadata and schemas.
- BaseTool: Abstract base class for all internal, Google, and MCP tools.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    async def aexecute(self, **kwargs: Any) -> Any:
        """Execute the tool asynchronously with supplied arguments.

        Args:
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
    "ToolDefinition",
    "ToolParameter",
]
