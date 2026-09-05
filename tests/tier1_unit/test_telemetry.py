"""Unit tests for Telemetry, Distributed Correlation ID, and Prometheus Metrics (OBS-01, OBS-04)."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from tars.adapters.router import CircuitState, LLMCircuitBreaker
from tars.core.telemetry import (
    CorrelationIdFilter,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
    tars_circuit_breaker_state,
    update_circuit_breaker_metric,
)


def test_correlation_id_context_lifecycle() -> None:
    """Verify set_correlation_id, get_correlation_id, and reset_correlation_id lifecycle."""
    assert get_correlation_id() == ""

    token = set_correlation_id("cid-lifecycle-001")
    try:
        assert get_correlation_id() == "cid-lifecycle-001"
    finally:
        reset_correlation_id(token)

    assert get_correlation_id() == ""


@pytest.mark.asyncio
async def test_correlation_id_async_inheritance() -> None:
    """Verify asyncio tasks inherit active correlation ID from calling context."""
    token = set_correlation_id("cid-async-parent-42")

    async def child_task() -> str:
        return get_correlation_id()

    try:
        task = asyncio.create_task(child_task())
        child_cid = await task
        assert child_cid == "cid-async-parent-42"
    finally:
        reset_correlation_id(token)


def test_correlation_id_logging_filter() -> None:
    """Verify CorrelationIdFilter injects correlation_id attribute into LogRecord."""
    log_filter = CorrelationIdFilter()

    # Case 1: When no correlation ID is set, injects "-"
    record_empty = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message without CID",
        args=(),
        exc_info=None,
    )
    assert log_filter.filter(record_empty) is True
    assert getattr(record_empty, "correlation_id") == "-"

    # Case 2: When correlation ID is set, injects the active ID
    token = set_correlation_id("cid-filter-test-99")
    try:
        record_with_cid = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=20,
            msg="Test message with CID",
            args=(),
            exc_info=None,
        )
        assert log_filter.filter(record_with_cid) is True
        assert getattr(record_with_cid, "correlation_id") == "cid-filter-test-99"
    finally:
        reset_correlation_id(token)


def test_update_circuit_breaker_metric_direct() -> None:
    """Verify update_circuit_breaker_metric sets gauge for all string and enum states."""
    update_circuit_breaker_metric("closed")
    assert tars_circuit_breaker_state._value.get() == 0.0

    update_circuit_breaker_metric("half_open")
    assert tars_circuit_breaker_state._value.get() == 1.0

    update_circuit_breaker_metric("open")
    assert tars_circuit_breaker_state._value.get() == 2.0

    update_circuit_breaker_metric(CircuitState.CLOSED)
    assert tars_circuit_breaker_state._value.get() == 0.0

    update_circuit_breaker_metric(CircuitState.HALF_OPEN)
    assert tars_circuit_breaker_state._value.get() == 1.0

    update_circuit_breaker_metric(CircuitState.OPEN)
    assert tars_circuit_breaker_state._value.get() == 2.0

    # With breaker_name argument
    update_circuit_breaker_metric("gemini", "closed")
    assert tars_circuit_breaker_state._value.get() == 0.0


def _get_cb_state(cb: LLMCircuitBreaker) -> str:
    return str(cb.state.value)


def test_circuit_breaker_state_transitions_update_metric() -> None:
    """Verify LLMCircuitBreaker state transitions automatically update Prometheus gauge."""
    cb = LLMCircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    assert _get_cb_state(cb) == "closed"
    assert tars_circuit_breaker_state._value.get() == 0.0

    # 1st failure - below threshold
    cb.record_failure()
    assert _get_cb_state(cb) == "closed"
    assert tars_circuit_breaker_state._value.get() == 0.0

    # 2nd failure - trips OPEN
    cb.record_failure()
    assert _get_cb_state(cb) == "open"
    assert tars_circuit_breaker_state._value.get() == 2.0

    # Request rejected while OPEN
    assert cb.allow_request() is False
    assert tars_circuit_breaker_state._value.get() == 2.0

    # Elapse recovery timeout
    time.sleep(0.12)

    # Transition to HALF_OPEN
    assert cb.allow_request() is True
    assert _get_cb_state(cb) == "half_open"
    assert tars_circuit_breaker_state._value.get() == 1.0

    # Canary succeeds -> CLOSED
    cb.record_success()
    assert _get_cb_state(cb) == "closed"
    assert tars_circuit_breaker_state._value.get() == 0.0

    # Trip and reset
    cb.record_failure()
    cb.record_failure()
    assert _get_cb_state(cb) == "open"
    assert tars_circuit_breaker_state._value.get() == 2.0

    cb.reset()
    assert _get_cb_state(cb) == "closed"
    assert tars_circuit_breaker_state._value.get() == 0.0
