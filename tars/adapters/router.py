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
import time
from collections.abc import AsyncIterator, Sequence
from enum import Enum, StrEnum
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from tars.adapters.base import BaseLLMAdapter, LLMResponse
from tars.config import get_settings

logger = logging.getLogger("tars.adapters.router")


class CircuitState(str, Enum):
    """Operational states of the upstream LLM circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


TACTICAL_UPLINK_SEVERED_PREFIX = "[Tactical Uplink Severed — Operating on Auxiliary Local Core] "
AUXILIARY_CORE_ACTIVE_PREFIX = "[Auxiliary Tactical Core Active] "


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
                "Gemini Circuit Breaker TRIPPED OPEN (failures=%d, threshold=%d). Routing traffic to local SLM fallback.",
                self.failure_count,
                self.failure_threshold,
            )

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
        self._half_open_in_flight = False
        self._half_open_timestamp = 0.0


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
        circuit_breaker: LLMCircuitBreaker | None = None,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        auxiliary_prefix: str = TACTICAL_UPLINK_SEVERED_PREFIX,
    ) -> None:
        self.gemini_adapter = gemini_adapter
        self.slm_adapter = slm_adapter
        timeout = (
            slm_timeout_ms if slm_timeout_ms is not None else get_settings().llamacpp_timeout_ms
        )
        self.slm_timeout_ms = timeout
        self.slm_timeout_sec = timeout / 1000.0
        self.circuit_breaker = circuit_breaker or LLMCircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
        self.auxiliary_prefix = auxiliary_prefix

    async def aclose(self) -> None:
        """Close underlying LLM client adapters."""
        if hasattr(self.slm_adapter, "aclose") and callable(self.slm_adapter.aclose):
            await self.slm_adapter.aclose()
        elif hasattr(self.slm_adapter, "close") and callable(self.slm_adapter.close):
            res = self.slm_adapter.close()
            if asyncio.iscoroutine(res):
                await res

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
        """의도 분류 및 헬스 체크 기반 타깃 LLM/SLM 엔진 평가 라우팅.

        [아키텍처 원칙]:
        1. 사용자 대화 응답(User-Facing Response, user_facing=True):
           - TARS 고유 페르소나(유머 90%, 정직 95%) 및 지식 융합을 위해 Google Gemini 100% 전담.
        2. 내부 경량 추론(Internal Preprocessing, user_facing=False):
           - 빠른 의도 분류, 단순 전처리, 키워드 추출 등은 로컬 SLM(llama.cpp) 전담 (초저지연, 비용 0원).
        3. 500ms Fallback Circuit Breaker:
           - 로컬 SLM 비정상/타임아웃 발생 시 Gemini로 즉각 자동 Fallback.
        """
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

        # 사용자 대면 발화(User-Facing)인 경우 아키텍처 원칙에 따라 Gemini 전담
        if user_facing:
            return RoutingDecision(
                target_engine=LLMEngineType.GEMINI,
                reason="user_facing_response",
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
        user_facing: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """의도 기반 쿼리 라우팅 및 500ms 서킷 브레이커 Fallback 실시간 토큰 스트리밍."""
        decision = await self.evaluate_routing(
            messages=messages, force_engine=force_engine, user_facing=user_facing
        )

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
            except asyncio.CancelledError:
                raise
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning(
                    "SLM streaming failed or timed out (%s). Falling back to Gemini.", err_detail
                )
                if self.circuit_breaker.allow_request():
                    try:
                        async for chunk in self.gemini_adapter.astream(
                            messages=messages,
                            system_prompt=system_prompt,
                            **kwargs,
                        ):
                            yield chunk
                        self.circuit_breaker.record_success()
                        return
                    except asyncio.CancelledError:
                        self.circuit_breaker.record_cancellation()
                        raise
                    except Exception as gemini_err:
                        self.circuit_breaker.record_failure()
                        logger.error("Both SLM and Gemini failed during stream: %s", gemini_err)
                        raise
                else:
                    raise

        # Target engine is GEMINI
        if self.circuit_breaker.allow_request():
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
                return
            except asyncio.CancelledError:
                self.circuit_breaker.record_cancellation()
                raise
            except Exception as gemini_err:
                err_detail = (
                    f"{type(gemini_err).__name__}: {gemini_err}"
                    if str(gemini_err)
                    else type(gemini_err).__name__
                )
                logger.warning(
                    "Gemini streaming failed (%s). Engaging local SLM fallback.", err_detail
                )
                self.circuit_breaker.record_failure()
                if first_chunk_yielded:
                    # Stream was partially delivered; cannot cleanly prepend prefix without corrupting stream
                    raise

        # Fallback to local SLM
        logger.info("Executing local SLM fallback streaming for query.")
        if self.auxiliary_prefix:
            yield self.auxiliary_prefix
        async for chunk in self.slm_adapter.astream(
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
        user_facing: bool = False,
        **kwargs: Any,
    ) -> str:
        """단일 턴 텍스트 완결 생성 (회로 차단기 Fallback 지원)."""
        decision = await self.evaluate_routing(
            messages=messages, force_engine=force_engine, user_facing=user_facing
        )

        if decision.target_engine == LLMEngineType.SLM:
            try:
                return await asyncio.wait_for(
                    self.slm_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs),
                    timeout=self.slm_timeout_sec,
                )
            except asyncio.CancelledError:
                raise
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning("SLM generation failed (%s). Falling back to Gemini.", err_detail)
                if self.circuit_breaker.allow_request():
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
                        self.circuit_breaker.record_failure()
                        logger.error("Both SLM and Gemini failed: %s", gemini_err)
                        raise
                raise

        # Target engine is GEMINI
        if self.circuit_breaker.allow_request():
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
                logger.warning(
                    "Gemini generation failed (%s). Engaging local SLM fallback.", err_detail
                )
                self.circuit_breaker.record_failure()

        # Fallback to local SLM
        logger.info("Executing local SLM fallback generation for query.")
        slm_res = await asyncio.wait_for(
            self.slm_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs),
            timeout=max(self.slm_timeout_sec, 5.0),
        )
        return f"{self.auxiliary_prefix}{slm_res}"

    async def route_and_generate_response(
        self,
        messages: Sequence[BaseMessage],
        system_prompt: str = "",
        force_engine: LLMEngineType | None = None,
        user_facing: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """구조화된 도구 호출(ToolCallData)을 포함한 LLMResponse 생성 및 라우팅."""
        tools = kwargs.get("tools")
        # 도구가 전달되었거나 사용자 대면 발화인 경우 Gemini 우선 라우팅
        effective_force = force_engine
        if effective_force is None and tools and len(tools) > 0:
            effective_force = LLMEngineType.GEMINI

        decision = await self.evaluate_routing(
            messages=messages, force_engine=effective_force, user_facing=user_facing
        )

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
            except asyncio.CancelledError:
                raise
            except Exception as slm_err:
                err_detail = (
                    f"{type(slm_err).__name__}: {slm_err}"
                    if str(slm_err)
                    else type(slm_err).__name__
                )
                logger.warning("SLM generation failed (%s). Falling back to Gemini.", err_detail)

        # Target engine is GEMINI
        if self.circuit_breaker.allow_request():
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
                logger.warning(
                    "Gemini response generation failed (%s). Engaging local SLM fallback.",
                    err_detail,
                )
                self.circuit_breaker.record_failure()

        # Fallback to local SLM
        logger.info("Executing local SLM fallback for structured response.")
        if hasattr(self.slm_adapter, "agenerate_response"):
            slm_resp = await asyncio.wait_for(
                self.slm_adapter.agenerate_response(
                    messages, system_prompt=system_prompt, **kwargs
                ),
                timeout=max(self.slm_timeout_sec, 5.0),
            )
            return LLMResponse(
                content=f"{self.auxiliary_prefix}{slm_resp.content}",
                tool_calls=slm_resp.tool_calls,
            )
        text = await asyncio.wait_for(
            self.slm_adapter.agenerate(messages, system_prompt=system_prompt, **kwargs),
            timeout=max(self.slm_timeout_sec, 5.0),
        )
        return LLMResponse(content=f"{self.auxiliary_prefix}{text}", tool_calls=[])

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
