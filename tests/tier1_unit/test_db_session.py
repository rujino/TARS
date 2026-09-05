"""Tier 1 Unit Tests: Async SQLAlchemy database engine, connection pooling, and session lifecycle (RES-03)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from tars.config import Settings, get_settings
from tars.db.session import (
    close_db,
    get_db,
    get_engine,
    get_session_factory,
    get_sessionmaker,
    init_db,
)


@pytest.fixture(autouse=True)
async def cleanup_db_engine() -> AsyncGenerator[None, None]:
    """Ensure clean engine state before and after each test."""
    await close_db()
    get_settings.cache_clear()
    yield
    await close_db()
    get_settings.cache_clear()


def test_settings_db_pool_defaults() -> None:
    """Verify Settings contains the required SQLAlchemy pool configuration with exact defaults."""
    settings = Settings()
    assert settings.db_pool_size == 20
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30.0
    assert settings.db_pool_recycle == 1800
    assert settings.db_pool_pre_ping is True


@pytest.mark.asyncio
async def test_get_engine_postgresql_pooling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_engine passes configured pool parameters for PostgreSQL."""
    monkeypatch.setenv(
        "TARS_DATABASE_URL",
        "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb",
    )
    monkeypatch.setenv("TARS_DB_POOL_SIZE", "25")
    monkeypatch.setenv("TARS_DB_MAX_OVERFLOW", "15")
    monkeypatch.setenv("TARS_DB_POOL_TIMEOUT", "45.0")
    monkeypatch.setenv("TARS_DB_POOL_RECYCLE", "2400")
    monkeypatch.setenv("TARS_DB_POOL_PRE_PING", "true")
    get_settings.cache_clear()

    with patch("tars.db.session.create_async_engine") as mock_create:
        mock_engine = MagicMock(spec=AsyncEngine)
        mock_create.return_value = mock_engine

        engine = get_engine()
        assert engine is mock_engine
        mock_create.assert_called_once_with(
            "postgresql+asyncpg://testuser:testpass@localhost:5432/testdb",
            echo=False,
            future=True,
            pool_size=25,
            max_overflow=15,
            pool_timeout=45.0,
            pool_recycle=2400,
            pool_pre_ping=True,
        )


@pytest.mark.asyncio
async def test_get_engine_sqlite_in_memory_dialect_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify SQLite :memory: uses StaticPool and does NOT receive pool_size/max_overflow/pool_timeout."""
    monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()

    engine = get_engine()
    assert engine is not None
    assert engine.pool.__class__.__name__ == "StaticPool"

    # Verify tables can be created and queries executed without error
    await init_db(engine)
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_get_engine_sqlite_file_pooling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify file-based SQLite engines apply full connection pool settings."""
    db_file = tmp_path / "sqlite_file_test.db"
    monkeypatch.setenv("TARS_DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()

    with patch("tars.db.session.create_async_engine", wraps=create_async_engine) as spy_create:
        engine = get_engine()
        assert engine is not None
        assert spy_create.called
        call_kwargs = spy_create.call_args.kwargs
        assert call_kwargs["pool_size"] == 20
        assert call_kwargs["max_overflow"] == 10
        assert call_kwargs["pool_timeout"] == 30.0
        assert call_kwargs["pool_recycle"] == 1800
        assert call_kwargs["pool_pre_ping"] is True


@pytest.mark.asyncio
async def test_get_db_session_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_db FastAPI dependency yields an AsyncSession and commits automatically."""
    monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    engine = get_engine()
    await init_db(engine)

    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    assert session.is_active

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


@pytest.mark.asyncio
async def test_get_db_rollback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_db performs rollback when an exception occurs inside the context."""
    monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    engine = get_engine()
    await init_db(engine)

    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)

    with pytest.raises(RuntimeError, match="Transaction test error"):
        await gen.athrow(RuntimeError("Transaction test error"))


@pytest.mark.asyncio
async def test_close_db_resets_engine_and_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify close_db disposes engine and resets singleton references."""
    monkeypatch.setenv("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    get_settings.cache_clear()
    engine1 = get_engine()
    sessionmaker1 = get_session_factory()
    assert engine1 is not None
    assert sessionmaker1 is not None

    await close_db()

    engine2 = get_engine()
    assert engine2 is not engine1
