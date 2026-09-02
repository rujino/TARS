"""Alembic environment configuration for async SQLAlchemy and TARS models."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import tars.db.models  # noqa: F401 - Ensure all models are registered on Base.metadata
from tars.config import get_settings
from tars.db.base import Base

# Alembic Config object, which provides access to values in alembic.ini
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_target_db_url() -> str:
    """Resolve database URL dynamically from environment, config, or settings."""
    explicit_url = config.get_main_option("sqlalchemy.url")
    if explicit_url:
        return explicit_url

    env_url = os.environ.get("TARS_DATABASE_URL")
    if env_url:
        return env_url

    try:
        return get_settings().database_url
    except Exception:
        return explicit_url or "postgresql+asyncpg://tarsuser:tarspassword@localhost:5432/tars"


# Target metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without an active DB connection."""
    url = get_target_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations inside a synchronous connection context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Establish async engine connection and execute migrations synchronously."""
    target_url = get_target_db_url()
    configuration: dict[str, Any] = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = target_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with async connection execution."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
