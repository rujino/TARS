"""FastAPI Application Factory for TARS."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Ensure all domain models are loaded into Base.metadata before table creation
import tars.domains.auth.models  # noqa: F401
import tars.domains.chat.models  # noqa: F401
import tars.domains.knowledge.models  # noqa: F401
import tars.domains.persona.models  # noqa: F401
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
    yield

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

    # PWA Root Endpoints
    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        index_file = settings.static_dir / "index.html"
        if not index_file.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PWA index.html not found.",
            )
        return FileResponse(index_file)

    @app.get("/manifest.json", include_in_schema=False)
    async def serve_manifest() -> FileResponse:
        manifest_file = settings.static_dir / "manifest.json"
        if not manifest_file.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PWA manifest.json not found.",
            )
        return FileResponse(
            manifest_file,
            media_type="application/manifest+json",
        )

    @app.get("/sw.js", include_in_schema=False)
    async def serve_sw() -> FileResponse:
        sw_file = settings.static_dir / "sw.js"
        if not sw_file.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PWA sw.js not found.",
            )
        return FileResponse(
            sw_file,
            media_type="application/javascript",
        )

    # Mount Static Files Directory
    if settings.static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(settings.static_dir)),
            name="static",
        )

    return app


__all__ = ["create_app"]
