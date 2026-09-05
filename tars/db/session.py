"""Async SQLAlchemy database engine, session factory, and FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tars.config import get_settings
from tars.db.base import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create singleton AsyncEngine instance."""
    global _engine
    if _engine is None:
        settings = get_settings()

        engine_kwargs: dict[str, Any] = {
            "echo": settings.db_echo,
            "future": True,
        }

        # StaticPool (e.g. SQLite :memory:) does not support pool_size, max_overflow, or pool_timeout
        if "sqlite" in settings.database_url and ":memory:" in settings.database_url:
            engine_kwargs["pool_pre_ping"] = settings.db_pool_pre_ping
            engine_kwargs["pool_recycle"] = settings.db_pool_recycle
        else:
            engine_kwargs.update(
                {
                    "pool_size": settings.db_pool_size,
                    "max_overflow": settings.db_max_overflow,
                    "pool_timeout": settings.db_pool_timeout,
                    "pool_recycle": settings.db_pool_recycle,
                    "pool_pre_ping": settings.db_pool_pre_ping,
                }
            )

        _engine = create_async_engine(
            settings.database_url,
            **engine_kwargs,
        )

    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Get or create singleton async_sessionmaker instance."""
    global _sessionmaker
    if _sessionmaker is None:
        engine = get_engine()
        _sessionmaker = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


get_session_factory = get_sessionmaker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an AsyncSession with automatic transaction handling."""
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all database tables (for development/testing lifespan)."""
    target_engine = engine or get_engine()
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the database engine (for lifespan shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


__all__ = [
    "close_db",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_sessionmaker",
    "init_db",
]
