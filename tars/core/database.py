"""Database engine, declarative base, and session management."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from tars.config import get_settings
from tars.core.security import decrypt_secret, encrypt_secret


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy TypeDecorator that encrypts data on bind and decrypts on load."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return encrypt_secret(value) if value is not None else value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return decrypt_secret(value) if value is not None else value


# Standard naming convention for PostgreSQL/SQLite database constraints.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_`%(constraint_name)s`",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Mixin adding created_at and updated_at UTC datetime columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Mixin adding a 36-character UUID string primary key."""

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )


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
    """Create all database tables (for lifespan startup)."""
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
    "NAMING_CONVENTION",
    "Base",
    "EncryptedString",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "close_db",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_sessionmaker",
    "init_db",
]
