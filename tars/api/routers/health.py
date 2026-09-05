"""Health check and Prometheus metrics endpoints for TARS."""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from tars.api.dependencies import get_storage_manager
from tars.config import get_settings
from tars.db.session import get_session_factory

logger = logging.getLogger("tars.api.routers.health")

health_router = APIRouter(tags=["Health & Telemetry"])
router = health_router


@health_router.get("/health", include_in_schema=True)
@health_router.get("/health/liveness", include_in_schema=True)
async def liveness_check() -> dict[str, str]:
    """Lightweight liveness probe indicating application process is alive."""
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name}


@health_router.get("/health/readiness", include_in_schema=True)
async def readiness_check() -> JSONResponse:
    """Deep readiness probe testing active DB connectivity and storage accessibility.

    Returns HTTP 200 if all subsystems pass, or HTTP 503 if any probe fails.
    """
    settings = get_settings()
    is_ready = True
    db_status = "connected"
    storage_status = "accessible"
    errors: list[str] = []

    # 1. Database Probe (SELECT 1 with 1.0s timeout)
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=1.0)
    except Exception as exc:
        is_ready = False
        db_status = f"unhealthy: {exc}"
        errors.append(f"database: {exc}")
        logger.error("Readiness probe: database check failed: %s", exc, exc_info=True)

    # 2. File Storage Probe (Ephemeral write & delete probe file)
    try:
        storage = get_storage_manager()
        base_dir = storage.base_dir
        base_dir.mkdir(parents=True, exist_ok=True)
        probe_path = base_dir / f".health_probe_{uuid.uuid4().hex}"
        probe_path.touch(exist_ok=True)
        probe_path.unlink(missing_ok=True)
    except Exception as exc:
        is_ready = False
        storage_status = f"unhealthy: {exc}"
        errors.append(f"storage: {exc}")
        logger.error("Readiness probe: storage check failed: %s", exc, exc_info=True)

    if is_ready:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ready",
                "overall": "ok",
                "database": db_status,
                "storage": storage_status,
                "checks": {
                    "database": db_status,
                    "storage": storage_status,
                },
                "app": settings.app_name,
            },
        )

    error_detail = "; ".join(errors)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "degraded",
            "overall": "degraded",
            "database": db_status,
            "storage": storage_status,
            "error": error_detail,
            "checks": {
                "database": db_status,
                "storage": storage_status,
            },
            "app": settings.app_name,
        },
    )


@health_router.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    """Expose Prometheus telemetry metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = ["health_router", "router"]
