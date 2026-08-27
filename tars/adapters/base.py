"""Base LLM Adapter Interface and Supporting Data Models for TARS.

Provides:
- BaseLLMAdapter abstract base class with agenerate, astream, is_healthy, health_check.
- Strongly typed Pydantic models: ToolCallData, TokenUsage, LLMResponse, LLMStreamChunk.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field


class ToolCallData(BaseModel):
    """Structured representation of an LLM tool call invocation."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique tool call identifier")
    name: str = Field(..., description="Tool name to execute")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="JSON arguments for the tool"
    )


class TokenUsage(BaseModel):
    """Token usage metrics."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens consumed")


class LLMResponse(BaseModel):
    """Complete response payload from an LLM adapter."""

    model_config = ConfigDict(extra="ignore")

    content: str = Field(default="", description="Generated text content")
    tool_calls: list[ToolCallData] = Field(default_factory=list, description="Requested tool calls")
    finish_reason: str = Field(default="stop", description="Completion stop reason")
    usage: TokenUsage | None = Field(default=None, description="Token consumption metadata")
    model_name: str = Field(default="", description="Name of the responding model")

    def __str__(self) -> str:
        return self.content

    def __contains__(self, item: str) -> bool:
        return item in self.content

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.content == other
        if isinstance(other, LLMResponse):
            return self.content == other.content
        return super().__eq__(other)


class LLMStreamChunk(BaseModel):
    """Single incremental chunk from an LLM token stream."""

    model_config = ConfigDict(extra="ignore")

    delta_content: str = Field(default="", description="Incremental text token delta")
    tool_call_chunks: list[ToolCallData] = Field(
        default_factory=list, description="Incremental tool call fragments"
    )
    is_final: bool = Field(default=False, description="Flag indicating final stream chunk")
    usage: TokenUsage | None = Field(
        default=None, description="Token usage (usually on final chunk)"
    )


class BaseLLMAdapter(ABC):
    """Abstract Base Class unifying all LLM and SLM providers in TARS."""

    @abstractmethod
    def astream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response tokens in real time asynchronously.

        Args:
            messages: Conversation message history.
            system_prompt: Persona and knowledge context instructions.
            **kwargs: Additional model-specific hyperparameters.

        Yields:
            str: Token chunks as they arrive.
        """

    @abstractmethod
    async def agenerate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Generate a complete text response asynchronously.

        Args:
            messages: Conversation message history.
            system_prompt: Persona and knowledge context instructions.
            **kwargs: Additional model-specific hyperparameters.

        Returns:
            str: The full generated response content.
        """

    async def agenerate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a complete LLMResponse including content and tool calls.

        Args:
            messages: Conversation message history.
            system_prompt: Persona and knowledge context instructions.
            **kwargs: Additional model-specific hyperparameters.

        Returns:
            LLMResponse: Structured response model.
        """
        text = await self.agenerate(messages, system_prompt=system_prompt, **kwargs)
        return LLMResponse(content=text, tool_calls=[])

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Probe the adapter endpoint to verify reachability and operational health.

        Returns:
            bool: True if healthy and ready to serve requests, False otherwise.
        """

    async def health_check(self, timeout: float = 0.5) -> bool:
        """Perform health probe with a strict timeout cutoff.

        Args:
            timeout: Maximum allowed probe duration in seconds (default: 0.5s / 500ms).

        Returns:
            bool: True if probe succeeds within timeout, False otherwise.
        """
        try:
            return await asyncio.wait_for(self.is_healthy(), timeout=timeout)
        except Exception:
            return False

    async def check_health(self) -> bool:
        """Alias for is_healthy for test and integration compatibility."""
        return await self.is_healthy()

    def bind_tools(self, tools: Sequence[dict[str, Any]]) -> BaseLLMAdapter:
        """Bind tool definitions for function calling (optional default implementation)."""
        return self


__all__ = [
    "BaseLLMAdapter",
    "LLMResponse",
    "LLMStreamChunk",
    "TokenUsage",
    "ToolCallData",
]
