"""Hybrid LLM Router with Intent Classification and 500ms Fallback Circuit Breaker.

Provides:
- LLMEngineType enum (GEMINI, SLM)
- RoutingDecision Pydantic model
- HybridLLMRouter: intent classification, fast health check, and dynamic fallback.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from tars.adapters.base import BaseLLMAdapter, LLMResponse
from tars.config import get_settings

logger = logging.getLogger("tars.adapters.router")


class LLMEngineType(StrEnum):
    """Supported LLM backend execution engines."""

    GEMINI = "gemini"
    SLM = "slm"


class RoutingDecision(BaseModel):
    """Result of intent classification and routing evaluation."""

    model_config = ConfigDict(frozen=True)

    target_engine: LLMEngineType = Field(..., description="Selected LLM execution engine")
    reason: str = Field(..., description="Rationale for routing decision")
    is_fallback: bool = Field(
        default=False, description="True if decision is a fallback from unhealthy SLM"
    )


# Regex patterns for intent classification
COMPLEX_REASONING_PATTERNS = re.compile(
    r"\b(calculate|orbit|orbital|mechanics|trajectory|dilation|gravitational|gargantua|"
    r"physics|relativity|quantum|math|equation|formula|code|python|script|sql|query|"
    r"database|search|lookup|schedule|calendar|meeting|analyze|analysis|compare|design|"
    r"architecture|synthesize|procedure|algorithm|explain\s+in\s+detail|diagnose)\b",
    re.IGNORECASE,
)

CASUAL_CHAT_PATTERNS = re.compile(
    r"\b(hello|hi|hey|greetings|good\s+morning|good\s+evening|good\s+afternoon|"
    r"how\s+are\s+you|how\'s\s+it\s+going|what\'s\s+up|who\s+are\s+you|tell\s+me\s+a\s+joke|"
    r"joke|status\s+report|standing\s+by|quick\s+hello|ready|thank\s+you|thanks|"
    r"안녕|안녕하세요|반가워|하이|고마워|감사합니다|상태\s*보고|농담\s*해봐|너\s*누구야)\b",
    re.IGNORECASE,
)


class HybridLLMRouter:
    """Intelligent router orchestrating cloud Gemini and local llama.cpp SLM engines."""

    def __init__(
        self,
        gemini_adapter: BaseLLMAdapter,
        slm_adapter: BaseLLMAdapter,
        slm_timeout_ms: int | None = None,
    ) -> None:
        self.gemini_adapter = gemini_adapter
        self.slm_adapter = slm_adapter
        timeout = (
            slm_timeout_ms if slm_timeout_ms is not None else get_settings().llamacpp_timeout_ms
        )
        self.slm_timeout_ms = timeout
        self.slm_timeout_sec = timeout / 1000.0

    async def evaluate_routing(
        self,
        messages: Sequence[BaseMessage],
        force_engine: LLMEngineType | None = None,
    ) -> RoutingDecision:
        """Evaluate messages to select target engine with health probe checking."""
        if force_engine is not None:
            return RoutingDecision(
                target_engine=force_engine,
                reason="forced_override",
                is_fallback=False,
            )

        if not messages:
            return RoutingDecision(
                target_engine=LLMEngineType.GEMINI,
                reason="empty_messages",
                is_fallback=False,
            )

        # Extract latest user message content
        user_texts: list[str] = [str(m.content) for m in messages if isinstance(m, HumanMessage)]
        last_text = user_texts[-1] if user_texts else str(messages[-1].content)

        # 1. Complex reasoning / tool execution check -> Gemini
        if COMPLEX_REASONING_PATTERNS.search(last_text):
            return RoutingDecision(
                target_engine=LLMEngineType.GEMINI,
                reason="complex_reasoning",
                is_fallback=False,
            )

        # 2. Casual chat check -> SLM if healthy, otherwise fallback to Gemini
        if CASUAL_CHAT_PATTERNS.search(last_text):
            is_slm_healthy = await self.slm_adapter.is_healthy()
            if is_slm_healthy:
                return RoutingDecision(
                    target_engine=LLMEngineType.SLM,
                    reason="casual_chat",
                    is_fallback=False,
                )
            else:
                return RoutingDecision(
                    target_engine=LLMEngineType.GEMINI,
                    reason="casual_chat",
                    is_fallback=True,
                )

        # 3. Default fallback for unclassified messages -> Gemini
        return RoutingDecision(
            target_engine=LLMEngineType.GEMINI,
            reason="complex_reasoning",
            is_fallback=False,
        )

    async def route_and_stream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Route query and stream response with 500ms circuit breaker fallback."""
        decision = await self.evaluate_routing(messages=messages, force_engine=force_engine)

        if decision.target_engine == LLMEngineType.SLM:
            try:
                stream_iter = self.slm_adapter.astream(
                    messages=messages,
                    system_prompt=system_prompt,
                    **kwargs,
                )
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            stream_iter.__anext__(),
                            timeout=self.slm_timeout_sec,
                        )
                        yield chunk
                    except StopAsyncIteration:
                        break
                return
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning(
                    "SLM streaming failed or timed out (%s). Falling back to Gemini.", err_detail
                )
                async for chunk in self.gemini_adapter.astream(
                    messages=messages,
                    system_prompt=system_prompt,
                    **kwargs,
                ):
                    yield chunk
                return

        # Direct Gemini execution
        async for chunk in self.gemini_adapter.astream(
            messages=messages,
            system_prompt=system_prompt,
            **kwargs,
        ):
            yield chunk

    async def route_and_generate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        **kwargs: Any,
    ) -> str:
        """Route query and generate complete text with circuit breaker fallback."""
        decision = await self.evaluate_routing(messages=messages, force_engine=force_engine)

        if decision.target_engine == LLMEngineType.SLM:
            try:
                return await asyncio.wait_for(
                    self.slm_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs),
                    timeout=self.slm_timeout_sec,
                )
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning("SLM generation failed (%s). Falling back to Gemini.", err_detail)
                return await self.gemini_adapter.agenerate(
                    messages, system_prompt=system_prompt, **kwargs
                )

        return await self.gemini_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs)

    async def route_and_generate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Route query and generate structured LLMResponse with tool calls."""
        tools = kwargs.get("tools")
        # If tools are bound/passed, route to Gemini by default unless forced
        effective_force = force_engine
        if effective_force is None and tools and len(tools) > 0:
            effective_force = LLMEngineType.GEMINI

        decision = await self.evaluate_routing(messages=messages, force_engine=effective_force)

        if decision.target_engine == LLMEngineType.SLM:
            try:
                if hasattr(self.slm_adapter, "agenerate_response"):
                    return await asyncio.wait_for(
                        self.slm_adapter.agenerate_response(
                            messages, system_prompt=system_prompt, **kwargs
                        ),
                        timeout=self.slm_timeout_sec,
                    )
                text = await asyncio.wait_for(
                    self.slm_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs),
                    timeout=self.slm_timeout_sec,
                )
                return LLMResponse(content=text, tool_calls=[])
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning("SLM generation failed (%s). Falling back to Gemini.", err_detail)

        if hasattr(self.gemini_adapter, "agenerate_response"):
            return await self.gemini_adapter.agenerate_response(
                messages, system_prompt=system_prompt, **kwargs
            )
        text = await self.gemini_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs)
        return LLMResponse(content=text, tool_calls=[])

    async def agenerate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate structured response (BaseLLMAdapter interface)."""
        return await self.route_and_generate_response(
            messages=messages, system_prompt=system_prompt, **kwargs
        )

    async def agenerate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """Route query and generate complete text (BaseLLMAdapter interface)."""
        return await self.route_and_generate(
            messages=messages, system_prompt=system_prompt, **kwargs
        )

    async def astream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Route query and stream tokens (BaseLLMAdapter interface)."""
        async for chunk in self.route_and_stream(
            messages=messages, system_prompt=system_prompt, **kwargs
        ):
            yield chunk


__all__ = [
    "HybridLLMRouter",
    "LLMEngineType",
    "RoutingDecision",
]
