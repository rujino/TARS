"""Tier 1 Unit Tests: Cloud LLM Resilience & Circuit Breaker (REL-01).

Verifies:
1. LLMCircuitBreaker state machine (CLOSED, OPEN, HALF_OPEN) transitions.
2. Consecutive failure threshold tripping circuit to OPEN.
3. Recovery timeout triggering HALF_OPEN canary trial.
4. Canary success restoring CLOSED state and resetting failure count.
5. Canary failure re-tripping circuit to OPEN.
6. Cancellation hygiene: asyncio.CancelledError is re-raised and does not record circuit failure.
7. HybridLLMRouter fallback from Gemini to SLM in route_and_generate, route_and_stream, and route_and_generate_response.
8. In-character tactical prefix prepended on SLM fallback.
9. Fast short-circuiting to SLM without calling Gemini when circuit is OPEN.
10. Full lifecycle recovery flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from tars.adapters.base import BaseLLMAdapter, LLMResponse, ToolCallData
from tars.adapters.router import (
    TACTICAL_UPLINK_SEVERED_PREFIX,
    CircuitState,
    HybridLLMRouter,
    LLMCircuitBreaker,
)


class FakeMockAdapter(BaseLLMAdapter):
    """Configurable mock adapter for router resilience testing."""

    def __init__(
        self,
        name: str = "mock",
        response_text: str = "ok",
        should_fail: bool = False,
        fail_exception: Exception | None = None,
        tool_calls: list[ToolCallData] | None = None,
    ) -> None:
        self.name = name
        self.response_text = response_text
        self.should_fail = should_fail
        self.fail_exception = fail_exception or RuntimeError(f"{name} failure")
        self.tool_calls = tool_calls or []
        self.generate_call_count = 0
        self.stream_call_count = 0
        self.response_call_count = 0

    async def is_healthy(self) -> bool:
        return not self.should_fail

    async def agenerate(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        self.generate_call_count += 1
        if self.should_fail:
            raise self.fail_exception
        return self.response_text

    async def astream(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self.stream_call_count += 1
        if self.should_fail:
            raise self.fail_exception
        for word in self.response_text.split():
            yield word + " "

    async def agenerate_response(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        self.response_call_count += 1
        if self.should_fail:
            raise self.fail_exception
        return LLMResponse(content=self.response_text, tool_calls=self.tool_calls)


# ============================================================================
# 1. LLMCircuitBreaker State Machine Tests
# ============================================================================


def test_circuit_breaker_initial_closed_state() -> None:
    """Verify circuit breaker initializes in CLOSED state with allow_request=True."""
    cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb.allow_request() is True


def test_circuit_breaker_success_resets_failures() -> None:
    """Verify record_success() resets failure_count to 0."""
    cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.failure_count == 2
    assert cb.state == CircuitState.CLOSED

    cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_circuit_breaker_trips_to_open_after_threshold() -> None:
    """Verify reaching failure_threshold transitions state to OPEN and blocks requests."""
    cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_circuit_breaker_transitions_to_half_open_after_timeout() -> None:
    """Verify circuit transitions to HALF_OPEN after recovery_timeout elapses."""
    cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Before timeout
    assert cb.allow_request() is False

    # Simulate time elapse by modifying last_failure_time
    cb.last_failure_time -= 2.0
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN


def test_circuit_breaker_half_open_success_restores_closed() -> None:
    """Verify successful canary probe in HALF_OPEN transitions circuit back to CLOSED."""
    cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    cb.record_failure()
    cb.record_failure()
    cb.last_failure_time -= 2.0
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb.allow_request() is True


def test_circuit_breaker_half_open_failure_re_opens() -> None:
    """Verify failed canary probe in HALF_OPEN immediately re-trips circuit to OPEN."""
    cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    cb.record_failure()
    cb.record_failure()
    cb.last_failure_time -= 2.0
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


# ============================================================================
# 2. HybridLLMRouter Fallback & Cancellation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_route_and_generate_gemini_failure_triggers_slm_fallback() -> None:
    """Verify Gemini exception triggers fallback to SLM with tactical prefix."""
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="Local SLM response")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
    )

    messages = [HumanMessage(content="TARS, calculate orbital decay.")]
    result = await router.route_and_generate(messages, user_facing=True)

    assert result.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert "Local SLM response" in result
    assert gemini.generate_call_count == 1
    assert slm.generate_call_count == 1
    assert router.circuit_breaker.failure_count == 1
    assert router.circuit_breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_route_and_generate_circuit_open_skips_gemini() -> None:
    """Verify when circuit is OPEN, Gemini is skipped completely and SLM responds directly."""
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="Operating autonomously.")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=2,
    )

    # Trip the circuit
    router.circuit_breaker.record_failure()
    router.circuit_breaker.record_failure()
    assert router.circuit_breaker.state == CircuitState.OPEN

    messages = [HumanMessage(content="Status report")]
    result = await router.route_and_generate(messages, user_facing=True)

    assert result.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert "Operating autonomously." in result
    # Gemini should NOT have been called because circuit was OPEN
    assert gemini.generate_call_count == 0
    assert slm.generate_call_count == 1


@pytest.mark.asyncio
async def test_route_and_stream_gemini_failure_triggers_slm_fallback() -> None:
    """Verify Gemini stream failure yields tactical prefix followed by SLM chunks."""
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="Streaming from local core")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
    )

    messages = [HumanMessage(content="Tell me a joke")]
    chunks: list[str] = []
    async for chunk in router.route_and_stream(messages, user_facing=True):
        chunks.append(chunk)

    full_output = "".join(chunks)
    assert full_output.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert "Streaming from local core" in full_output
    assert router.circuit_breaker.failure_count == 1


@pytest.mark.asyncio
async def test_route_and_stream_circuit_open_directs_to_slm() -> None:
    """Verify when circuit is OPEN, streaming bypasses Gemini and yields prefix + SLM stream."""
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="Direct local stream")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=1,
    )
    router.circuit_breaker.record_failure()
    assert router.circuit_breaker.state == CircuitState.OPEN

    messages = [HumanMessage(content="Quick update")]
    chunks: list[str] = []
    async for chunk in router.route_and_stream(messages, user_facing=True):
        chunks.append(chunk)

    full_output = "".join(chunks)
    assert full_output.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert "Direct local stream" in full_output
    assert gemini.stream_call_count == 0


@pytest.mark.asyncio
async def test_route_and_generate_response_fallback_preserves_tools() -> None:
    """Verify structured response generation falls back to SLM with tactical prefix while preserving tool calls."""
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    sample_tools = [ToolCallData(id="call_001", name="search", arguments={"query": "mars"})]
    slm = FakeMockAdapter(
        name="slm",
        response_text="Structured SLM plan",
        tool_calls=sample_tools,
    )
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
    )

    messages = [HumanMessage(content="Plan search")]
    resp = await router.route_and_generate_response(messages, user_facing=True)

    assert isinstance(resp, LLMResponse)
    assert resp.content.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert "Structured SLM plan" in resp.content
    assert resp.tool_calls == sample_tools


@pytest.mark.asyncio
async def test_circuit_breaker_cancellation_hygiene() -> None:
    """Verify asyncio.CancelledError during generation is re-raised and does NOT count as a circuit failure."""
    async def cancelling_agenerate(*args: Any, **kwargs: Any) -> str:
        raise asyncio.CancelledError()

    gemini = FakeMockAdapter(name="gemini")
    gemini.agenerate = cancelling_agenerate  # type: ignore[method-assign]
    slm = FakeMockAdapter(name="slm")
    router = HybridLLMRouter(gemini_adapter=gemini, slm_adapter=slm)

    messages = [HumanMessage(content="Cancelled task")]
    with pytest.raises(asyncio.CancelledError):
        await router.route_and_generate(messages, user_facing=True)

    # Failure count must remain 0
    assert router.circuit_breaker.failure_count == 0
    assert router.circuit_breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_recovery_flow_full_lifecycle() -> None:
    """End-to-end test of circuit breaker recovery lifecycle:
    CLOSED -> Failures -> OPEN -> Timeout -> HALF_OPEN (probe succeeds) -> CLOSED restored.
    """
    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="SLM core response")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
        recovery_timeout=0.05,  # 50ms recovery timeout
    )

    messages = [HumanMessage(content="Turn 1")]

    # 1. Cause 3 failures to trip circuit
    await router.route_and_generate(messages, user_facing=True)
    assert router.circuit_breaker.state == CircuitState.CLOSED
    await router.route_and_generate(messages, user_facing=True)
    assert router.circuit_breaker.state == CircuitState.CLOSED
    await router.route_and_generate(messages, user_facing=True)
    assert router.circuit_breaker.state == CircuitState.OPEN

    # 2. In OPEN state, fast-fails to SLM without calling Gemini
    gemini_calls_before = gemini.generate_call_count
    res_open = await router.route_and_generate(messages, user_facing=True)
    assert res_open.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert gemini.generate_call_count == gemini_calls_before

    # 3. Wait for recovery timeout to elapse
    await asyncio.sleep(0.06)

    # 4. Repair Gemini so canary probe succeeds
    gemini.should_fail = False
    gemini.response_text = "Gemini cloud core restored"

    # Canary turn executes and recovers circuit
    res_canary = await router.route_and_generate(messages, user_facing=True)
    assert res_canary == "Gemini cloud core restored"
    assert not res_canary.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert router.circuit_breaker.state == CircuitState.CLOSED
    assert router.circuit_breaker.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_cancellation_allows_subsequent_canary() -> None:
    """Verify cancelling an in-flight canary probe in HALF_OPEN resets in-flight flag,
    allowing subsequent requests to probe Gemini rather than permanently deadlocking.
    """
    block_event = asyncio.Event()

    async def blocking_agenerate(*args: Any, **kwargs: Any) -> str:
        await block_event.wait()
        return "gemini recovered"

    gemini = FakeMockAdapter(name="gemini", should_fail=True)
    slm = FakeMockAdapter(name="slm", response_text="SLM core backup")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=1,
        recovery_timeout=0.02,
    )

    # 1. Trip circuit to OPEN
    router.circuit_breaker.record_failure()
    assert router.circuit_breaker.state == CircuitState.OPEN

    # 2. Wait for recovery timeout to elapse
    await asyncio.sleep(0.03)

    # 3. Setup Gemini to block while in-flight
    gemini.should_fail = False
    gemini.agenerate = blocking_agenerate  # type: ignore[method-assign]

    messages = [HumanMessage(content="Canary probe")]
    canary_task = asyncio.create_task(router.route_and_generate(messages, user_facing=True))
    await asyncio.sleep(0.01)

    # Verify circuit entered HALF_OPEN
    assert router.circuit_breaker.state == CircuitState.HALF_OPEN

    # Cancel the in-flight canary task
    canary_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await canary_task

    # Circuit state must remain HALF_OPEN, but _half_open_in_flight must be False
    assert router.circuit_breaker.state == CircuitState.HALF_OPEN
    assert router.circuit_breaker._half_open_in_flight is False

    # 4. Unblock Gemini for the subsequent probe
    block_event.set()

    # 5. Subsequent request should be permitted as a canary probe and succeed
    res = await router.route_and_generate(messages, user_facing=True)
    assert res == "gemini recovered"
    assert router.circuit_breaker.state == CircuitState.CLOSED
    assert router.circuit_breaker.failure_count == 0


def test_circuit_breaker_half_open_timeout_safety_reset() -> None:
    """Verify allow_request resets _half_open_in_flight if canary probe exceeded recovery_timeout."""
    import time

    cb = LLMCircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    time.sleep(0.015)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN
    assert cb._half_open_in_flight is True

    # Immediate second request is diverted
    assert cb.allow_request() is False

    # After recovery timeout passes, safety reset permits new canary
    time.sleep(0.015)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN
    assert cb._half_open_in_flight is True

