"""FastAPI Application Factory for TARS."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tars.api.routers.auth import router as auth_router
from tars.api.routers.chat import router as chat_router
from tars.api.routers.config import router as config_router
from tars.config import get_settings
from tars.db.base import Base
from tars.db.session import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for database initialization and cleanup.

    NOTE: For MVP development speed, tables are auto-created via `Base.metadata.create_all`.
    Alembic migrations will be introduced in production. All models must adhere to `NAMING_CONVENTION`
    to ensure seamless future Alembic migration support.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


def create_app() -> FastAPI:
    """Create and configure a production FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.app_name} Core API",
        version="1.0.0",
        description="Tactical Autonomous Robotic System (TARS) - Core MVP Backend API",
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API Routers under /api/v1
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")
    app.include_router(chat_router, prefix="/api/v1")

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "app": settings.app_name}

    # PWA Root Endpoints
    @app.get("/", include_in_schema=False)
    async def serve_index() -> FileResponse:
        return FileResponse(settings.static_dir / "index.html")

    @app.get("/manifest.json", include_in_schema=False)
    async def serve_manifest() -> FileResponse:
        return FileResponse(
            settings.static_dir / "manifest.json",
            media_type="application/manifest+json",
        )

    @app.get("/sw.js", include_in_schema=False)
    async def serve_sw() -> FileResponse:
        return FileResponse(
            settings.static_dir / "sw.js",
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
