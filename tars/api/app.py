"""FastAPI Application Factory for TARS."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure all domain models are loaded into Base.metadata before table creation
import tars.domains.auth.models  # noqa: F401
import tars.domains.chat.models  # noqa: F401
import tars.domains.knowledge.models  # noqa: F401
import tars.domains.persona.models  # noqa: F401
import tars.domains.proactive.models  # noqa: F401
from tars.api.dependencies import close_tool_registry, get_tool_registry
from tars.api.routers import api_v1_router, health_router
from tars.config import get_settings
from tars.core.database import Base, close_db, get_engine
from tars.core.telemetry import CorrelationIdMiddleware, setup_telemetry_logging
from tars.engine.orchestrator.nodes import shutdown_background_tasks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for database initialization and cleanup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize ToolRegistry singleton on startup
    app.state.tool_registry = await get_tool_registry()

    # Initialize Proactive Coordinator and Scheduler on startup
    from tars.domains.proactive.coordinator import ProactiveCoordinator
    from tars.domains.proactive.scheduler.engine import ProactiveScheduler

    coordinator = ProactiveCoordinator()
    app.state.proactive_coordinator = coordinator
    proactive_scheduler = ProactiveScheduler(job_handler=coordinator.execute_for_user)
    await proactive_scheduler.start()
    app.state.proactive_scheduler = proactive_scheduler

    yield

    # Graceful Shutdown: Proactive scheduler
    if hasattr(app.state, "proactive_scheduler") and app.state.proactive_scheduler is not None:
        try:
            await app.state.proactive_scheduler.shutdown()
        except Exception:
            pass

    # Graceful Shutdown: Drain background knowledge extraction tasks cleanly
    await shutdown_background_tasks(timeout=5.0)

    # Close tool registry and underlying HTTP clients
    if hasattr(app.state, "tool_registry") and app.state.tool_registry is not None:
        try:
            await app.state.tool_registry.aclose()
        except Exception:
            pass
    await close_tool_registry()

    # Dispose of SQLAlchemy database engine connection pool
    await close_db()


def create_app() -> FastAPI:
    """Create and configure a production FastAPI instance."""
    settings = get_settings()

    # Configure logging with correlation ID injection
    setup_telemetry_logging()

    app = FastAPI(
        title=f"{settings.app_name} Core API",
        version="1.0.0",
        description="Tactical Autonomous Robotic System (TARS) - Core MVP Backend API",
        lifespan=lifespan,
    )

    # Correlation ID & Metrics Middleware
    app.add_middleware(CorrelationIdMiddleware)

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API v1 Routers under /api/v1
    app.include_router(api_v1_router, prefix="/api/v1")

    # Include Health & Telemetry Router (/health, /health/readiness, /metrics)
    app.include_router(health_router)

    return app


__all__ = ["create_app"]
