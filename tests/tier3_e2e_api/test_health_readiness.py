"""Tier 3 E2E API Tests for Observability, Deep Health Probing, and Metrics (OBS-01, OBS-03, OBS-04)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tars.api.app import create_app
from tars.config import get_settings


@pytest.mark.asyncio
async def test_health_liveness_endpoints() -> None:
    """Verify both /health and /health/liveness return 200 with application status."""
    settings = get_settings()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # /health
        res_health = await client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "ok", "app": settings.app_name}

        # /health/liveness
        res_liveness = await client.get("/health/liveness")
        assert res_liveness.status_code == 200
        assert res_liveness.json() == {"status": "ok", "app": settings.app_name}


@pytest.mark.asyncio
async def test_correlation_id_propagation_and_generation() -> None:
    """Verify X-Correlation-ID is echoed when supplied, or generated when omitted (OBS-01)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Custom correlation ID provided by client
        custom_cid = "trace-client-req-998877"
        res_custom = await client.get("/health", headers={"X-Correlation-ID": custom_cid})
        assert res_custom.status_code == 200
        assert res_custom.headers.get("X-Correlation-ID") == custom_cid

        # 2. No correlation ID provided -> server generates 32-hex UUID
        res_gen = await client.get("/health")
        assert res_gen.status_code == 200
        generated_cid = res_gen.headers.get("X-Correlation-ID")
        assert generated_cid is not None
        assert re.fullmatch(r"[0-9a-f]{32}", generated_cid) is not None


@pytest.mark.asyncio
async def test_readiness_probe_healthy() -> None:
    """Verify /health/readiness returns HTTP 200 when DB and storage are healthy (OBS-03)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/health/readiness")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["overall"] == "ok"
        assert data["database"] == "connected"
        assert data["storage"] == "accessible"
        assert data["checks"]["database"] == "connected"
        assert data["checks"]["storage"] == "accessible"


@pytest.mark.asyncio
async def test_readiness_probe_database_failure() -> None:
    """Verify /health/readiness returns HTTP 503 when database is unreachable (OBS-03)."""
    app = create_app()
    transport = ASGITransport(app=app)

    mock_session = AsyncMock()
    mock_session.execute.side_effect = ConnectionRefusedError("Database connection refused")
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session_factory.return_value.__aexit__.return_value = None

    with patch("tars.api.routers.health.get_session_factory", return_value=mock_session_factory):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/health/readiness")
            assert res.status_code == 503
            data = res.json()
            assert data["status"] == "degraded"
            assert data["overall"] == "degraded"
            assert "unhealthy" in data["database"]
            assert "Database connection refused" in data["error"]
            assert data["storage"] == "accessible"


@pytest.mark.asyncio
async def test_readiness_probe_storage_failure() -> None:
    """Verify /health/readiness returns HTTP 503 when storage directory is inaccessible (OBS-03)."""
    app = create_app()
    transport = ASGITransport(app=app)

    mock_storage = MagicMock()
    mock_base_dir = MagicMock()
    mock_base_dir.mkdir.side_effect = PermissionError("Storage filesystem is read-only")
    mock_storage.base_dir = mock_base_dir

    with patch("tars.api.routers.health.get_storage_manager", return_value=mock_storage):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/health/readiness")
            assert res.status_code == 503
            data = res.json()
            assert data["status"] == "degraded"
            assert data["overall"] == "degraded"
            assert "unhealthy" in data["storage"]
            assert "Storage filesystem is read-only" in data["error"]
            assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint() -> None:
    """Verify /metrics exports Prometheus telemetry and records HTTP traffic (OBS-04)."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Send a request to trigger metrics recording
        ping_res = await client.get("/health")
        assert ping_res.status_code == 200

        # Retrieve Prometheus metrics
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers.get("content-type", "")

        metrics_body = res.text
        assert "tars_http_requests_total" in metrics_body
        assert "tars_http_request_duration_seconds" in metrics_body
        assert "tars_circuit_breaker_state" in metrics_body
        # Endpoint /health must have been observed
        assert 'endpoint="/health"' in metrics_body
