"""Centralized Telemetry, Distributed Tracing Context, and Prometheus Metrics for TARS."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# ============================================================================
# 1. Distributed Correlation ID Context
# ============================================================================

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    """Retrieve the current request correlation ID from contextvars."""
    return correlation_id_ctx.get()


def set_correlation_id(cid: str) -> contextvars.Token[str]:
    """Set the active correlation ID in the current async context."""
    return correlation_id_ctx.set(cid)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    """Reset the correlation ID to its previous context state."""
    correlation_id_ctx.reset(token)


class CorrelationIdFilter(logging.Filter):
    """Logging filter attaching the active correlation ID to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


# ============================================================================
# 2. Prometheus Metrics Registry
# ============================================================================

tars_http_requests_total = Counter(
    "tars_http_requests_total",
    "Total HTTP requests processed by endpoint and status code.",
    ["method", "endpoint", "status_code"],
)
HTTP_REQUESTS_TOTAL = tars_http_requests_total

tars_http_request_duration_seconds = Histogram(
    "tars_http_request_duration_seconds",
    "HTTP request latency distribution in seconds.",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUEST_DURATION_SECONDS = tars_http_request_duration_seconds

tars_circuit_breaker_state = Gauge(
    "tars_circuit_breaker_state",
    "Operational state of LLM circuit breaker (0=CLOSED, 1=HALF_OPEN, 2=OPEN).",
)
CIRCUIT_BREAKER_STATE = tars_circuit_breaker_state


def update_circuit_breaker_metric(
    state_or_name: str | Any,
    state_val: str | Any = None,
) -> None:
    """Update tars_circuit_breaker_state metric gauge.

    Accepts single state argument (e.g. "closed", "open", "half_open", CircuitState enum, or int)
    or two arguments (breaker_name, state).
    """
    effective_state = state_val if state_val is not None else state_or_name
    mapping = {"closed": 0.0, "half_open": 1.0, "open": 2.0}

    if isinstance(effective_state, (int, float)):
        val = float(effective_state)
    elif hasattr(effective_state, "value"):
        val = mapping.get(str(effective_state.value).lower(), 0.0)
    else:
        val = mapping.get(str(effective_state).lower(), 0.0)

    tars_circuit_breaker_state.set(val)


# ============================================================================
# 3. HTTP Observability Middleware
# ============================================================================

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware ensuring X-Correlation-ID propagation and HTTP metrics recording."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        corr_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        token = set_correlation_id(corr_id)
        start_time = time.monotonic()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Correlation-ID"] = corr_id
            return response
        finally:
            duration = time.monotonic() - start_time
            endpoint = request.url.path
            method = request.method

            # Record Prometheus metrics (skipping /metrics itself to prevent observer effect)
            if endpoint != "/metrics":
                tars_http_requests_total.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code=str(status_code),
                ).inc()
                tars_http_request_duration_seconds.labels(
                    method=method,
                    endpoint=endpoint,
                ).observe(duration)

            reset_correlation_id(token)


def setup_telemetry_logging() -> None:
    """Configure logging formatters with CorrelationIdFilter across root and tars loggers."""
    log_filter = CorrelationIdFilter()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s"
    )
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        default_handler = logging.StreamHandler()
        default_handler.setFormatter(formatter)
        default_handler.addFilter(log_filter)
        root_logger.addHandler(default_handler)
    else:
        for handler in root_logger.handlers:
            handler.addFilter(log_filter)
            handler.setFormatter(formatter)

    tars_logger = logging.getLogger("tars")
    for handler in tars_logger.handlers:
        handler.addFilter(log_filter)
        handler.setFormatter(formatter)


__all__ = [
    "CIRCUIT_BREAKER_STATE",
    "CONTENT_TYPE_LATEST",
    "CorrelationIdFilter",
    "CorrelationIdMiddleware",
    "HTTP_REQUEST_DURATION_SECONDS",
    "HTTP_REQUESTS_TOTAL",
    "correlation_id_ctx",
    "generate_latest",
    "get_correlation_id",
    "reset_correlation_id",
    "set_correlation_id",
    "setup_telemetry_logging",
    "tars_circuit_breaker_state",
    "tars_http_request_duration_seconds",
    "tars_http_requests_total",
    "update_circuit_breaker_metric",
]
