#!/usr/bin/env python3
"""Challenger 2 Standalone Empirical Stress-Testing Harness.

Evaluates TARS Phase 0 P0 Hardening for:
1. REL-01: LLMCircuitBreaker State Machine & Gemini-to-SLM Fallback
2. ASY-02: Async Password Security & Event Loop Non-blocking Hygiene
3. Adversarial Edge Cases:
   - Canary cancellation deadlock in HALF_OPEN state
   - Asymmetric 72-byte password truncation authentication lockout
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from tars.adapters.base import BaseLLMAdapter, LLMResponse, ToolCallData
from tars.adapters.router import (
    TACTICAL_UPLINK_SEVERED_PREFIX,
    CircuitState,
    HybridLLMRouter,
    LLMCircuitBreaker,
)
from tars.core.security import (
    get_password_hash,
    get_password_hash_async,
    verify_password,
    verify_password_async,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("challenger_harness")


class MockConfigurableAdapter(BaseLLMAdapter):
    """Mock LLM adapter with configurable failure and latency."""

    def __init__(
        self,
        name: str,
        response_text: str = "ok",
        should_fail: bool = False,
        delay: float = 0.0,
        tool_calls: list[ToolCallData] | None = None,
    ) -> None:
        self.name = name
        self.response_text = response_text
        self.should_fail = should_fail
        self.delay = delay
        self.tool_calls = tool_calls or []
        self.generate_calls = 0
        self.stream_calls = 0
        self.response_calls = 0

    async def is_healthy(self) -> bool:
        return not self.should_fail

    async def agenerate(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        self.generate_calls += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed during agenerate")
        return self.response_text

    async def astream(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self.stream_calls += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed during astream")
        for word in self.response_text.split():
            yield word + " "

    async def agenerate_response(
        self,
        messages: list[BaseMessage] | Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        self.response_calls += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed during agenerate_response")
        return LLMResponse(content=self.response_text, tool_calls=self.tool_calls)


def _check(condition: bool, msg: str = "") -> None:
    if not condition:
        raise AssertionError(msg)


def _get_cb_state(b: LLMCircuitBreaker) -> str:
    return str(b.state.value)


def _allow_req(b: LLMCircuitBreaker) -> bool:
    return bool(b.allow_request())


# ============================================================================
# Test 1: Circuit Breaker State Machine Transitions
# ============================================================================
def test_circuit_breaker_state_machine() -> bool:
    """Verify CLOSED -> 3 failures -> OPEN -> cooldown -> HALF_OPEN -> CLOSED on success."""
    logger.info("=== Running Test 1: LLMCircuitBreaker State Machine ===")
    cb = LLMCircuitBreaker(failure_threshold=3, recovery_timeout=0.05)

    # 1. Initial CLOSED
    _check(_get_cb_state(cb) == CircuitState.CLOSED.value, f"Initial state should be CLOSED, got {cb.state}")
    _check(cb.failure_count == 0, f"Initial failures should be 0, got {cb.failure_count}")
    _check(_allow_req(cb) is True, "allow_request should be True in CLOSED")

    # 2. 1st and 2nd failures
    cb.record_failure()
    _check(_get_cb_state(cb) == CircuitState.CLOSED.value and cb.failure_count == 1)
    _check(_allow_req(cb) is True)

    cb.record_failure()
    _check(_get_cb_state(cb) == CircuitState.CLOSED.value and cb.failure_count == 2)
    _check(_allow_req(cb) is True)

    # 3. 3rd failure trips to OPEN
    cb.record_failure()
    _check(_get_cb_state(cb) == CircuitState.OPEN.value, f"Expected OPEN after 3 failures, got {cb.state}")
    _check(cb.failure_count == 3)
    _check(_allow_req(cb) is False, "allow_request should be False in OPEN before cooldown")

    # 4. Wait for cooldown (recovery_timeout = 0.05s)
    time.sleep(0.06)

    # 5. Transition to HALF_OPEN via canary allow_request()
    allowed = _allow_req(cb)
    _check(allowed is True, "Canary request should be allowed after cooldown")
    _check(_get_cb_state(cb) == CircuitState.HALF_OPEN.value, f"Expected HALF_OPEN, got {cb.state}")
    _check(cb._half_open_in_flight is True, "_half_open_in_flight should be True")

    # Concurrent request while canary in flight must be diverted (allow_request == False)
    _check(_allow_req(cb) is False, "Concurrent request during canary in flight should be blocked")

    # 6. Canary succeeds -> CLOSED restored
    cb.record_success()
    _check(_get_cb_state(cb) == CircuitState.CLOSED.value, f"Expected CLOSED on success, got {cb.state}")
    _check(cb.failure_count == 0, "failure_count should be reset to 0")
    _check(cb._half_open_in_flight is False)
    _check(_allow_req(cb) is True)

    # 7. Test HALF_OPEN failure re-tripping to OPEN
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    _check(_get_cb_state(cb) == CircuitState.OPEN.value)
    time.sleep(0.06)
    _check(_allow_req(cb) is True)
    _check(_get_cb_state(cb) == CircuitState.HALF_OPEN.value)

    cb.record_failure()
    _check(_get_cb_state(cb) == CircuitState.OPEN.value, f"Canary failure should re-trip to OPEN, got {cb.state}")
    _check(_allow_req(cb) is False)

    logger.info("--> Test 1 PASSED: LLMCircuitBreaker state machine transitions verified.")
    return True


# ============================================================================
# Test 2: Gemini Outage Fallback & Tactical Prefixing
# ============================================================================
async def test_gemini_outage_fallback() -> bool:
    """Verify Gemini failure and OPEN state fallback to SLM with tactical prefix."""
    logger.info("=== Running Test 2: Gemini Outage Fallback & Prefixing ===")
    gemini = MockConfigurableAdapter(name="gemini", should_fail=True)
    slm = MockConfigurableAdapter(
        name="slm",
        response_text="Auxiliary core responding cleanly.",
        tool_calls=[ToolCallData(id="call_99", name="status_probe", arguments={})],
    )
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
        recovery_timeout=10.0,
    )
    msgs = [HumanMessage(content="TARS, run diagnostic.")]

    # 1. route_and_generate fallback on exception
    res1 = await router.route_and_generate(msgs, user_facing=True)
    assert res1.startswith(TACTICAL_UPLINK_SEVERED_PREFIX), f"Prefix missing in res1: {res1}"
    assert "Auxiliary core responding cleanly." in res1
    assert gemini.generate_calls == 1
    assert slm.generate_calls == 1
    assert router.circuit_breaker.failure_count == 1

    # 2. route_and_stream fallback on exception
    chunks: list[str] = []
    async for chunk in router.route_and_stream(msgs, user_facing=True):
        chunks.append(chunk)
    stream_res = "".join(chunks)
    assert stream_res.startswith(TACTICAL_UPLINK_SEVERED_PREFIX), f"Prefix missing in stream: {stream_res}"
    assert "Auxiliary core responding cleanly." in stream_res
    assert gemini.stream_calls == 1
    assert router.circuit_breaker.failure_count == 2

    # 3. route_and_generate_response fallback on exception (trips circuit to OPEN)
    resp = await router.route_and_generate_response(msgs, user_facing=True)
    assert resp.content.startswith(TACTICAL_UPLINK_SEVERED_PREFIX), f"Prefix missing in resp: {resp.content}"
    assert resp.tool_calls == slm.tool_calls, "Tool calls must be preserved during SLM fallback"
    assert router.circuit_breaker.state == CircuitState.OPEN
    assert router.circuit_breaker.failure_count == 3

    # 4. In OPEN state, verify Gemini calls are completely skipped
    gemini_gen_before = gemini.generate_calls
    gemini_stream_before = gemini.stream_calls
    gemini_resp_before = gemini.response_calls

    res_open = await router.route_and_generate(msgs, user_facing=True)
    assert res_open.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert gemini.generate_calls == gemini_gen_before, "Gemini agenerate must not be called when OPEN"

    stream_open_chunks = [c async for c in router.route_and_stream(msgs, user_facing=True)]
    assert "".join(stream_open_chunks).startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert gemini.stream_calls == gemini_stream_before, "Gemini astream must not be called when OPEN"

    resp_open = await router.route_and_generate_response(msgs, user_facing=True)
    assert resp_open.content.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
    assert gemini.response_calls == gemini_resp_before, "Gemini agenerate_response must not be called when OPEN"

    logger.info("--> Test 2 PASSED: Gemini outage fallback and prefixing verified.")
    return True


# ============================================================================
# Test 3: Event Loop Non-blocking Async Authentication
# ============================================================================
async def test_event_loop_nonblocking_auth() -> bool:
    """Verify 10ms heartbeat runs >= 20 ticks during concurrent password operations."""
    logger.info("=== Running Test 3: Event Loop Non-blocking Async Authentication ===")
    heartbeat_ticks = 0
    running = True

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while running:
            await asyncio.sleep(0.01)  # 10ms
            heartbeat_ticks += 1

    hb_task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.02)  # initialize loop

    known_password = "CooperTARSMission2026!#"
    known_hash = get_password_hash(known_password)

    try:
        # Launch 6 concurrent password hashes and 6 concurrent verifications simultaneously
        tasks: list[asyncio.Task[Any]] = []
        for i in range(6):
            tasks.append(asyncio.create_task(get_password_hash_async(f"SecurePass_{i}_Entropy")))
            tasks.append(asyncio.create_task(verify_password_async(known_password, known_hash)))

        results = await asyncio.gather(*tasks)
        assert len(results) == 12

        logger.info("Total heartbeat ticks recorded during async bcrypt: %d", heartbeat_ticks)
        assert heartbeat_ticks >= 20, (
            f"Event loop blocked! Heartbeat ticks recorded: {heartbeat_ticks} (minimum required: 20)"
        )
    finally:
        running = False
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    # Contrast with synchronous baseline
    sync_heartbeat_ticks = 0
    sync_running = True

    async def sync_heartbeat() -> None:
        nonlocal sync_heartbeat_ticks
        while sync_running:
            await asyncio.sleep(0.01)
            sync_heartbeat_ticks += 1

    sync_hb_task = asyncio.create_task(sync_heartbeat())
    await asyncio.sleep(0.02)
    ticks_before = sync_heartbeat_ticks

    # Execute 6 sync hashes and 6 sync verifications directly on main thread
    for i in range(6):
        get_password_hash(f"SyncPass_{i}")
        verify_password(known_password, known_hash)

    ticks_during_sync = sync_heartbeat_ticks - ticks_before
    sync_running = False
    sync_hb_task.cancel()
    try:
        await sync_hb_task
    except asyncio.CancelledError:
        pass

    logger.info(
        "Empirical contrast: Async ticks = %d vs. Sync ticks = %d (Sync froze loop for 100%% of duration)",
        heartbeat_ticks,
        ticks_during_sync,
    )
    assert ticks_during_sync < 5, "Sync bcrypt unexpectedly allowed event loop ticks"

    logger.info("--> Test 3 PASSED: Event loop non-blocking hygiene verified.")
    return True


# ============================================================================
# Adversarial Challenge 1: Canary Cancellation Lockout in HALF_OPEN
# ============================================================================
async def challenge_canary_cancellation_lockout() -> tuple[bool, str]:
    """Test what happens if the canary probe is cancelled in HALF_OPEN state."""
    logger.info("=== Running Adversarial Challenge 1: Canary Cancellation Lockout ===")
    gemini = MockConfigurableAdapter(name="gemini", response_text="Gemini restored", delay=0.2)
    slm = MockConfigurableAdapter(name="slm", response_text="SLM core active")
    router = HybridLLMRouter(
        gemini_adapter=gemini,
        slm_adapter=slm,
        failure_threshold=3,
        recovery_timeout=0.05,
    )
    msgs = [HumanMessage(content="Query")]

    # Trip breaker to OPEN
    for _ in range(3):
        gemini.should_fail = True
        await router.route_and_generate(msgs, user_facing=True)

    assert _get_cb_state(router.circuit_breaker) == CircuitState.OPEN.value
    logger.info("Circuit tripped to OPEN.")

    # Wait for recovery timeout
    await asyncio.sleep(0.06)

    # Launch canary request and cancel it while awaiting gemini
    gemini.should_fail = False
    canary_task = asyncio.create_task(router.route_and_generate(msgs, user_facing=True))
    await asyncio.sleep(0.03)  # wait until in-flight
    canary_task.cancel()
    try:
        await canary_task
    except asyncio.CancelledError:
        logger.info("Canary task was cancelled during in-flight Gemini call.")

    logger.info(
        "State after cancellation: state=%s, _half_open_in_flight=%s",
        router.circuit_breaker.state,
        router.circuit_breaker._half_open_in_flight,
    )

    # Wait long enough for another cooldown window
    await asyncio.sleep(0.1)

    # Attempt subsequent request: should Gemini be probed?
    subsequent_res = await router.route_and_generate(msgs, user_facing=True)
    logger.info("Subsequent request result: %s", subsequent_res)

    is_locked = (
        _get_cb_state(router.circuit_breaker) == CircuitState.HALF_OPEN.value
        and router.circuit_breaker._half_open_in_flight is True
        and subsequent_res.startswith(TACTICAL_UPLINK_SEVERED_PREFIX)
        and router.circuit_breaker.allow_request() is False
    )

    if is_locked:
        msg = (
            "CRITICAL BUG CONFIRMED: Canary cancellation permanently deadlocks circuit breaker in HALF_OPEN. "
            "allow_request() returns False indefinitely and Gemini is never called again!"
        )
        logger.error(msg)
        return False, msg

    return True, "No canary cancellation deadlock observed."


# ============================================================================
# Adversarial Challenge 2: Asymmetric 72-Byte Password Truncation Lockout
# ============================================================================
async def challenge_password_length_asymmetry() -> tuple[bool, str]:
    """Test whether passwords > 72 bytes can be verified after hashing."""
    logger.info("=== Running Adversarial Challenge 2: Asymmetric Password Truncation ===")
    long_passwords = [
        ("Long ASCII (80 chars)", "A" * 80),
        ("Korean Passphrase (29 chars = 75 bytes)", "인터스텔라_우주선_엔듀어런스호_타스_쿠퍼_머프_블랜드"),
    ]

    lockouts: list[str] = []
    for label, pwd in long_passwords:
        utf8_bytes = len(pwd.encode("utf-8"))
        hashed = await get_password_hash_async(pwd)
        verified = await verify_password_async(pwd, hashed)
        logger.info("%s (%d bytes): Hashed=OK, Verified=%s", label, utf8_bytes, verified)
        if not verified:
            lockouts.append(f"{label} ({utf8_bytes} bytes): signup succeeded, login failed")

    if lockouts:
        msg = (
            f"HIGH BUG CONFIRMED: Asymmetric 72-byte truncation in security.py. "
            f"get_password_hash truncates to 72 bytes but verify_password does not truncate, "
            f"causing bcrypt.checkpw to raise ValueError and lock users out: {'; '.join(lockouts)}"
        )
        logger.error(msg)
        return False, msg

    return True, "All long passwords verified correctly."


# ============================================================================
# Main Runner
# ============================================================================
async def main() -> int:
    logger.info("Starting Challenger 2 Empirical Stress Test Harness...")
    results: dict[str, bool] = {}
    adversarial_findings: list[str] = []

    # Required Functional Verifications
    try:
        results["REL-01 State Machine"] = test_circuit_breaker_state_machine()
    except Exception as exc:
        logger.error("Test 1 FAILED with exception: %s", exc, exc_info=True)
        results["REL-01 State Machine"] = False

    try:
        results["REL-01 Gemini Fallback"] = await test_gemini_outage_fallback()
    except Exception as exc:
        logger.error("Test 2 FAILED with exception: %s", exc, exc_info=True)
        results["REL-01 Gemini Fallback"] = False

    try:
        results["ASY-02 Event Loop Hygiene"] = await test_event_loop_nonblocking_auth()
    except Exception as exc:
        logger.error("Test 3 FAILED with exception: %s", exc, exc_info=True)
        results["ASY-02 Event Loop Hygiene"] = False

    # Adversarial Probes
    canary_ok, canary_msg = await challenge_canary_cancellation_lockout()
    if not canary_ok:
        adversarial_findings.append(canary_msg)

    pwd_ok, pwd_msg = await challenge_password_length_asymmetry()
    if not pwd_ok:
        adversarial_findings.append(pwd_msg)

    logger.info("==========================================================")
    logger.info("CHALLENGER 2 EMPIRICAL TEST SUITE SUMMARY:")
    for name, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        logger.info("  [%s] %s", status, name)

    logger.info("==========================================================")
    if adversarial_findings:
        logger.error("ADVERSARIAL STRESS TEST FINDINGS (%d defects found):", len(adversarial_findings))
        for idx, finding in enumerate(adversarial_findings, 1):
            logger.error("  %d. %s", idx, finding)
        logger.info("==========================================================")
        return 1
    else:
        logger.info("No adversarial vulnerabilities found. Clean run.")
        logger.info("==========================================================")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
