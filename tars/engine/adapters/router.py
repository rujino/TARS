"""LLM Router with Gemini Engine and Circuit Breaker Resilience.

Provides:
- LLMEngineType enum (GEMINI)
- RoutingDecision Pydantic model
- HybridLLMRouter: unified Gemini routing with circuit breaker protection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Sequence
from enum import Enum, StrEnum
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

from tars.core.telemetry import update_circuit_breaker_metric
from tars.engine.adapters.base import BaseLLMAdapter, LLMResponse

logger = logging.getLogger("tars.adapters.router")


class CircuitState(str, Enum):
    """Operational states of the upstream LLM circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


TACTICAL_UPLINK_SEVERED_PREFIX = ""
AUXILIARY_CORE_ACTIVE_PREFIX = ""


class LLMCircuitBreaker:
    """Stateful circuit breaker guarding external cloud LLM API calls."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.state: CircuitState = CircuitState.CLOSED
        update_circuit_breaker_metric(self.state.value)
        self._half_open_in_flight: bool = False
        self._half_open_timestamp: float = 0.0

    def record_success(self) -> None:
        """Record successful invocation, resetting failure counter and closing circuit."""
        if self.state != CircuitState.CLOSED:
            logger.info(
                "Gemini Circuit Breaker RECOVERED: probe succeeded, state transitioned to CLOSED."
            )
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        update_circuit_breaker_metric(self.state.value)
        self._half_open_in_flight = False
        self._half_open_timestamp = 0.0

    def record_failure(self) -> None:
        """Record execution failure, incrementing counter and tripping open if threshold met."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        self._half_open_in_flight = False
        self._half_open_timestamp = 0.0

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(
                "Gemini Circuit Breaker TRIPPED OPEN (failures=%d, threshold=%d).",
                self.failure_count,
                self.failure_threshold,
            )
        update_circuit_breaker_metric(self.state.value)

    def record_cancellation(self) -> None:
        """Reset in-flight canary probe flag upon cancellation in HALF_OPEN state."""
        if self.state == CircuitState.HALF_OPEN:
            self._half_open_in_flight = False
            logger.info("Canary probe cancelled in HALF_OPEN state; reset in-flight flag.")

    def allow_request(self) -> bool:
        """Determine whether an upstream request is permitted according to state machine."""
        if self.state == CircuitState.CLOSED:
            return True

        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                update_circuit_breaker_metric(self.state.value)
                self._half_open_in_flight = True
                self._half_open_timestamp = now
                logger.info(
                    "Gemini Circuit Breaker recovery timeout (%.1fs) elapsed. Transitioning to HALF_OPEN (canary probe).",
                    self.recovery_timeout,
                )
                return True
            return False

        # self.state == CircuitState.HALF_OPEN
        # Safety recovery: if canary probe in HALF_OPEN was abandoned or timed out, reset flag
        if self._half_open_in_flight and (now - self._half_open_timestamp >= self.recovery_timeout):
            logger.warning(
                "Canary probe in HALF_OPEN timed out after %.1fs; resetting in-flight flag.",
                now - self._half_open_timestamp,
            )
            self._half_open_in_flight = False

        # Permit a single canary request; divert concurrent traffic
        if not self._half_open_in_flight:
            self._half_open_in_flight = True
            self._half_open_timestamp = now
            return True
        return False

    def reset(self) -> None:
        """Manually reset circuit breaker to pristine CLOSED state."""
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = CircuitState.CLOSED
        update_circuit_breaker_metric(self.state.value)
        self._half_open_in_flight = False
        self._half_open_timestamp = 0.0


class LLMEngineType(StrEnum):
    """Supported LLM backend execution engines."""

    GEMINI = "gemini"


class RoutingDecision(BaseModel):
    """Result of routing evaluation."""

    model_config = ConfigDict(frozen=True)

    target_engine: LLMEngineType = Field(..., description="Selected LLM execution engine")
    reason: str = Field(..., description="Rationale for routing decision")
    is_fallback: bool = Field(default=False, description="True if decision is a fallback")


class HybridLLMRouter:
    """Unified router orchestrating cloud Gemini LLM engine with circuit breaker protection."""

    def __init__(
        self,
        gemini_adapter: BaseLLMAdapter | None = None,
        circuit_breaker: LLMCircuitBreaker | None = None,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        auxiliary_prefix: str = "",
    ) -> None:
        if gemini_adapter is None:
            from tars.engine.adapters.gemini import GeminiAdapter

            self.gemini_adapter: BaseLLMAdapter = GeminiAdapter()
        else:
            self.gemini_adapter = gemini_adapter

        self.circuit_breaker = circuit_breaker or LLMCircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self.auxiliary_prefix = auxiliary_prefix

    async def aclose(self) -> None:
        """Close underlying LLM client adapters."""
        if hasattr(self.gemini_adapter, "aclose") and callable(self.gemini_adapter.aclose):
            await self.gemini_adapter.aclose()
        elif hasattr(self.gemini_adapter, "close") and callable(self.gemini_adapter.close):
            res = self.gemini_adapter.close()
            if asyncio.iscoroutine(res):
                await res

    async def close(self) -> None:
        """Alias for aclose."""
        await self.aclose()

    async def evaluate_routing(
        self,
        messages: Sequence[BaseMessage],
        force_engine: LLMEngineType | None = None,
        user_facing: bool = False,
    ) -> RoutingDecision:
        """Unified Gemini routing evaluation."""
        return RoutingDecision(
            target_engine=LLMEngineType.GEMINI,
            reason="unified_gemini",
            is_fallback=False,
        )

    async def route_and_stream(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        user_facing: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream tokens directly via Gemini with circuit breaker guard."""
        if not self.circuit_breaker.allow_request():
            raise RuntimeError("Gemini Circuit Breaker is OPEN; request rejected.")

        first_chunk_yielded = False
        try:
            stream_iter = self.gemini_adapter.astream(
                messages=messages,
                system_prompt=system_prompt,
                **kwargs,
            )
            async for chunk in stream_iter:
                if not first_chunk_yielded:
                    self.circuit_breaker.record_success()
                    first_chunk_yielded = True
                yield chunk
            if not first_chunk_yielded:
                self.circuit_breaker.record_success()
        except asyncio.CancelledError:
            self.circuit_breaker.record_cancellation()
            raise
        except Exception as gemini_err:
            err_detail = (
                f"{type(gemini_err).__name__}: {gemini_err}"
                if str(gemini_err)
                else type(gemini_err).__name__
            )
            logger.error("Gemini streaming failed (%s)", err_detail, exc_info=True)
            self.circuit_breaker.record_failure()
            raise

    async def route_and_generate(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        user_facing: bool = False,
        **kwargs: Any,
    ) -> str:
        """Generate complete response text directly via Gemini with circuit breaker guard."""
        if not self.circuit_breaker.allow_request():
            raise RuntimeError("Gemini Circuit Breaker is OPEN; request rejected.")

        try:
            res = await self.gemini_adapter.agenerate(
                messages, system_prompt=system_prompt, **kwargs
            )
            self.circuit_breaker.record_success()
            return res
        except asyncio.CancelledError:
            self.circuit_breaker.record_cancellation()
            raise
        except Exception as gemini_err:
            err_detail = (
                f"{type(gemini_err).__name__}: {gemini_err}"
                if str(gemini_err)
                else type(gemini_err).__name__
            )
            logger.error("Gemini generation failed (%s)", err_detail, exc_info=True)
            self.circuit_breaker.record_failure()
            raise

    async def route_and_generate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        user_facing: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate structured LLMResponse directly via Gemini with circuit breaker guard."""
        if not self.circuit_breaker.allow_request():
            raise RuntimeError("Gemini Circuit Breaker is OPEN; request rejected.")

        try:
            if hasattr(self.gemini_adapter, "agenerate_response"):
                resp = await self.gemini_adapter.agenerate_response(
                    messages, system_prompt=system_prompt, **kwargs
                )
            else:
                text = await self.gemini_adapter.agenerate(
                    messages, system_prompt=system_prompt, **kwargs
                )
                resp = LLMResponse(content=text, tool_calls=[])
            self.circuit_breaker.record_success()
            return resp
        except asyncio.CancelledError:
            self.circuit_breaker.record_cancellation()
            raise
        except Exception as gemini_err:
            err_detail = (
                f"{type(gemini_err).__name__}: {gemini_err}"
                if str(gemini_err)
                else type(gemini_err).__name__
            )
            logger.error("Gemini response generation failed (%s)", err_detail, exc_info=True)
            self.circuit_breaker.record_failure()
            raise

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
    "AUXILIARY_CORE_ACTIVE_PREFIX",
    "CircuitState",
    "HybridLLMRouter",
    "LLMCircuitBreaker",
    "LLMEngineType",
    "RoutingDecision",
    "TACTICAL_UPLINK_SEVERED_PREFIX",
]
