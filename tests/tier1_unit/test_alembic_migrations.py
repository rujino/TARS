"""Unit tests for Alembic database migrations and schema drift verification."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import tars.db.models  # noqa: F401 - Ensure all models are registered on Base.metadata
from tars.db.base import Base


def _get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _build_alembic_config(db_url: str) -> Config:
    """Construct an Alembic Config object pointing to the test database and migration scripts."""
    root = _get_project_root()
    ini_path = root / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.mark.asyncio
async def test_alembic_migration_upgrade_to_head_and_downgrade_to_base(tmp_path: Path) -> None:
    """Verify that Alembic applies migrations cleanly to SQLite head and downgrades to base."""
    test_db_file = tmp_path / "test_alembic_full_cycle.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db_file}"

    alembic_cfg = _build_alembic_config(test_db_url)

    original_env = os.environ.get("TARS_DATABASE_URL")
    os.environ["TARS_DATABASE_URL"] = test_db_url

    try:
        # 1. Run upgrade to head in thread to prevent event loop collision
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        # 2. Inspect database tables using async SQLAlchemy engine
        engine = create_async_engine(test_db_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            )
            tables = {str(row[0]) for row in result.fetchall()}

            expected_tables = {
                "users",
                "tars_settings",
                "user_wikis",
                "chat_sessions",
                "chat_messages",
                "alembic_version",
            }
            assert expected_tables.issubset(tables), (
                f"Missing tables after upgrade: {expected_tables - tables}"
            )

            # Verify columns on users table
            users_cols_res = await conn.execute(text("PRAGMA table_info(users);"))
            user_cols = {str(row[1]) for row in users_cols_res.fetchall()}
            assert {"id", "username", "email", "hashed_password", "is_active", "created_at", "updated_at"}.issubset(user_cols)

            # Verify columns on tars_settings table
            settings_cols_res = await conn.execute(text("PRAGMA table_info(tars_settings);"))
            settings_cols = {str(row[1]) for row in settings_cols_res.fetchall()}
            assert {"id", "user_id", "humor_level", "honesty_level", "mode", "created_at", "updated_at"}.issubset(settings_cols)

            # Verify columns on user_wikis table
            wikis_cols_res = await conn.execute(text("PRAGMA table_info(user_wikis);"))
            wikis_cols = {str(row[1]) for row in wikis_cols_res.fetchall()}
            assert {
                "id",
                "user_id",
                "okf_id",
                "okf_version",
                "type",
                "title",
                "category",
                "tags",
                "importance",
                "source",
                "relations",
                "file_path",
                "file_hash",
                "created_at",
                "updated_at",
            }.issubset(wikis_cols)

            # Verify columns on chat_sessions table
            sessions_cols_res = await conn.execute(text("PRAGMA table_info(chat_sessions);"))
            sessions_cols = {str(row[1]) for row in sessions_cols_res.fetchall()}
            assert {
                "id",
                "user_id",
                "title",
                "status",
                "bridge_summary",
                "parent_session_id",
                "last_active_at",
                "created_at",
                "updated_at",
            }.issubset(sessions_cols)

            # Verify columns on chat_messages table
            messages_cols_res = await conn.execute(text("PRAGMA table_info(chat_messages);"))
            messages_cols = {str(row[1]) for row in messages_cols_res.fetchall()}
            assert {"id", "session_id", "user_id", "role", "content", "tokens", "created_at"}.issubset(messages_cols)

        await engine.dispose()

        # 3. Run downgrade to base in thread
        await asyncio.to_thread(command.downgrade, alembic_cfg, "base")

        # 4. Verify application tables are dropped
        engine = create_async_engine(test_db_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            )
            remaining_tables = {str(row[0]) for row in result.fetchall()}
            # Application entity tables must be completely removed
            app_tables = {"users", "tars_settings", "user_wikis", "chat_sessions", "chat_messages"}
            assert not remaining_tables.intersection(app_tables), (
                f"Application tables still present after downgrade: {remaining_tables.intersection(app_tables)}"
            )

        await engine.dispose()

    finally:
        if original_env is not None:
            os.environ["TARS_DATABASE_URL"] = original_env
        else:
            os.environ.pop("TARS_DATABASE_URL", None)


@pytest.mark.asyncio
async def test_alembic_upgrade_downgrade_idempotency(tmp_path: Path) -> None:
    """Verify that multiple upgrade/downgrade cycles execute with 100% repeatability."""
    test_db_file = tmp_path / "test_idempotency.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db_file}"

    alembic_cfg = _build_alembic_config(test_db_url)

    original_env = os.environ.get("TARS_DATABASE_URL")
    os.environ["TARS_DATABASE_URL"] = test_db_url

    try:
        # Cycle 1: upgrade -> downgrade
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        await asyncio.to_thread(command.downgrade, alembic_cfg, "base")

        # Cycle 2: upgrade -> downgrade
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

        # Verify tables exist after re-upgrade
        engine = create_async_engine(test_db_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            )
            tables = {str(row[0]) for row in result.fetchall()}
            assert {"users", "tars_settings", "user_wikis", "chat_sessions", "chat_messages"}.issubset(tables)
        await engine.dispose()

        await asyncio.to_thread(command.downgrade, alembic_cfg, "base")

    finally:
        if original_env is not None:
            os.environ["TARS_DATABASE_URL"] = original_env
        else:
            os.environ.pop("TARS_DATABASE_URL", None)


def test_alembic_check_metadata_integrity() -> None:
    """Verify that all 5 target ORM models are registered in Base.metadata with expected columns."""
    registered_tables = set(Base.metadata.tables.keys())
    expected_tables = {
        "users",
        "tars_settings",
        "user_wikis",
        "chat_sessions",
        "chat_messages",
    }
    assert expected_tables.issubset(registered_tables), (
        f"Missing tables in Base.metadata: {expected_tables - registered_tables}"
    )

    # Check users table metadata
    users_table = Base.metadata.tables["users"]
    user_col_names = {c.name for c in users_table.columns}
    assert {"id", "username", "email", "hashed_password", "is_active", "created_at", "updated_at"}.issubset(user_col_names)

    # Check tars_settings table metadata
    settings_table = Base.metadata.tables["tars_settings"]
    settings_col_names = {c.name for c in settings_table.columns}
    assert {"id", "user_id", "humor_level", "honesty_level", "mode", "created_at", "updated_at"}.issubset(settings_col_names)

    # Check user_wikis table metadata
    wikis_table = Base.metadata.tables["user_wikis"]
    wikis_col_names = {c.name for c in wikis_table.columns}
    assert {
        "id",
        "user_id",
        "okf_id",
        "okf_version",
        "type",
        "title",
        "category",
        "tags",
        "importance",
        "source",
        "relations",
        "file_path",
        "file_hash",
        "created_at",
        "updated_at",
    }.issubset(wikis_col_names)

    # Check chat_sessions table metadata
    sessions_table = Base.metadata.tables["chat_sessions"]
    sessions_col_names = {c.name for c in sessions_table.columns}
    assert {
        "id",
        "user_id",
        "title",
        "status",
        "bridge_summary",
        "parent_session_id",
        "last_active_at",
        "created_at",
        "updated_at",
    }.issubset(sessions_col_names)

    # Check chat_messages table metadata
    messages_table = Base.metadata.tables["chat_messages"]
    messages_col_names = {c.name for c in messages_table.columns}
    assert {"id", "session_id", "user_id", "role", "content", "tokens", "created_at"}.issubset(messages_col_names)


def test_alembic_ini_configuration_file() -> None:
    """Verify that alembic.ini exists and has valid configuration settings."""
    root = _get_project_root()
    ini_path = root / "alembic.ini"
    assert ini_path.is_file(), f"alembic.ini missing at {ini_path}"

    content = ini_path.read_text(encoding="utf-8")
    assert "script_location = migrations" in content
    assert "version_table = alembic_version" in content
    assert "[alembic]" in content


def test_alembic_migration_versions_script() -> None:
    """Verify that migrations/versions/0001_initial_schema.py exists with correct revision identifiers."""
    root = _get_project_root()
    version_dir = root / "migrations" / "versions"
    assert version_dir.is_dir(), f"migrations/versions directory missing at {version_dir}"

    version_files = list(version_dir.glob("*.py"))
    assert len(version_files) >= 1, "At least one migration version file must exist in migrations/versions"

    initial_schema_file = next((f for f in version_files if "initial_schema" in f.name), None)
    assert initial_schema_file is not None, "0001_initial_schema.py migration file is missing"

    content = initial_schema_file.read_text(encoding="utf-8")
    assert "def upgrade()" in content
    assert "def downgrade()" in content
    assert "op.create_table(" in content
    assert '"users"' in content
    assert '"tars_settings"' in content
    assert '"user_wikis"' in content
    assert '"chat_sessions"' in content
    assert '"chat_messages"' in content


@pytest.mark.asyncio
async def test_alembic_check_no_schema_drift(tmp_path: Path) -> None:
    """Verify that Alembic detects no schema drift against the ORM Base.metadata."""
    test_db_file = tmp_path / "test_check_drift.db"
    test_db_url = f"sqlite+aiosqlite:///{test_db_file}"

    alembic_cfg = _build_alembic_config(test_db_url)

    original_env = os.environ.get("TARS_DATABASE_URL")
    os.environ["TARS_DATABASE_URL"] = test_db_url

    try:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        await asyncio.to_thread(command.check, alembic_cfg)
    finally:
        if original_env is not None:
            os.environ["TARS_DATABASE_URL"] = original_env
        else:
            os.environ.pop("TARS_DATABASE_URL", None)

