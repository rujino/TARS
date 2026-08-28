"""Adversarial and empirical stress tests for Phase 4 Milestone 1 (Alembic Migrations & DB Schema).

Tests cover:
- Multi-cycle upgrade / downgrade stress testing (5 consecutive cycles)
- Offline migration SQL script generation
- Unique constraints verification (uq_user_wikis_user_okf_id, uq_tars_settings_user_id, username, email)
- Foreign key constraints, CASCADE deletes, and SET NULL behavior under PRAGMA foreign_keys = ON
- Direct ORM operations, querying, and complex JSON payload persistence on migrated SQLite databases
- Adversarial data handling: Unicode, emojis, massive strings, nested JSON trees
- Transaction rollback recovery under integrity errors
- Dynamic environment variable resolution via Alembic execution
- High concurrency reads and writes on Alembic-migrated database
- run_migrations.sh permission and execution logic verification
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tars.db.models import (
    ChatMessage,
    ChatSession,
    TARSSettings,
    User,
    UserWikiIndex,
)


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _build_alembic_config(db_url: str) -> Config:
    root = _get_project_root()
    ini_path = root / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _create_engine_with_fk(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url, echo=False)

    # Enable foreign keys for SQLite connections
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


class TestAlembicMigrationCyclesAndOffline:
    """Stress-test migration upgrade and downgrade cycles and offline mode."""

    @pytest.mark.asyncio
    async def test_repeated_multi_cycle_upgrade_downgrade(self, tmp_path: Path) -> None:
        """Execute 5 continuous cycles of upgrade->head and downgrade->base."""
        db_file = tmp_path / "multi_cycle_stress.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            for cycle in range(1, 6):
                # Upgrade to head
                await asyncio.to_thread(command.upgrade, cfg, "head")

                # Verify all 5 application tables + alembic_version exist
                engine = create_async_engine(db_url)
                async with engine.connect() as conn:
                    res = await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
                    )
                    tables = {str(r[0]) for r in res.fetchall()}
                    expected = {"users", "tars_settings", "user_wikis", "chat_sessions", "chat_messages", "alembic_version"}
                    assert expected.issubset(tables), f"Cycle {cycle}: Tables missing after upgrade: {expected - tables}"
                await engine.dispose()

                # Downgrade to base
                await asyncio.to_thread(command.downgrade, cfg, "base")

                # Verify application tables are gone
                engine = create_async_engine(db_url)
                async with engine.connect() as conn:
                    res = await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
                    )
                    tables = {str(r[0]) for r in res.fetchall()}
                    app_tables = {"users", "tars_settings", "user_wikis", "chat_sessions", "chat_messages"}
                    assert not tables.intersection(app_tables), f"Cycle {cycle}: Application tables left after downgrade: {tables.intersection(app_tables)}"
                await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_offline_sql_generation(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify that Alembic generates complete offline DDL SQL statements."""
        db_file = tmp_path / "offline_test.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head", sql=True)
            captured = capsys.readouterr()
            sql_output = captured.out

            assert "CREATE TABLE users" in sql_output
            assert "CREATE TABLE tars_settings" in sql_output
            assert "CREATE TABLE user_wikis" in sql_output
            assert "CREATE TABLE chat_sessions" in sql_output
            assert "CREATE TABLE chat_messages" in sql_output
            assert "CREATE TABLE alembic_version" in sql_output
            assert "uq_user_wikis_user_okf_id" in sql_output
            assert "ix_user_wikis_lookup" in sql_output
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_multiple_distinct_database_migrations(self, tmp_path: Path) -> None:
        """Verify that multiple distinct SQLite databases can be migrated cleanly and independently."""
        db_urls = [f"sqlite+aiosqlite:///{tmp_path}/distinct_db_{i}.db" for i in range(4)]

        orig_env = os.environ.get("TARS_DATABASE_URL")
        try:
            for url in db_urls:
                os.environ["TARS_DATABASE_URL"] = url
                cfg = _build_alembic_config(url)
                await asyncio.to_thread(command.upgrade, cfg, "head")

                engine = create_async_engine(url)
                async with engine.connect() as conn:
                    res = await conn.execute(text("SELECT count(*) FROM sqlite_master WHERE type='table';"))
                    count = res.scalar_one()
                    assert count >= 6
                await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)


class TestAlembicSchemaIndexesAndConstraints:
    """Empirically inspect and verify all indices, foreign keys, and unique constraints."""

    @pytest.fixture
    async def migrated_db(self, tmp_path: Path) -> AsyncGenerator[tuple[AsyncEngine, str], None]:
        db_file = tmp_path / "schema_inspect.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            engine = _create_engine_with_fk(db_url)
            yield engine, db_url
            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_indexes_created_accurately(self, migrated_db: tuple[AsyncEngine, str]) -> None:
        """Verify that all expected single-column and composite indexes are present."""
        engine, _ = migrated_db
        async with engine.connect() as conn:
            # Query index list
            res = await conn.execute(text("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index';"))
            index_rows = res.fetchall()
            index_names = {str(r[0]) for r in index_rows if r[0] is not None}

            expected_indexes = {
                "ix_users_username",
                "ix_users_email",
                "ix_tars_settings_user_id",
                "ix_user_wikis_user_id",
                "ix_user_wikis_okf_id",
                "ix_user_wikis_type",
                "ix_user_wikis_category",
                "ix_user_wikis_importance",
                "ix_user_wikis_lookup",
                "ix_user_wikis_user_category",
                "ix_chat_sessions_user_id",
                "ix_chat_sessions_status",
                "ix_chat_sessions_last_active_at",
                "ix_chat_messages_session_id",
                "ix_chat_messages_user_id",
                "ix_chat_messages_created_at",
            }

            for expected_ix in expected_indexes:
                assert expected_ix in index_names, f"Index {expected_ix} not found in sqlite_master"

    @pytest.mark.asyncio
    async def test_composite_indexes_columns(self, migrated_db: tuple[AsyncEngine, str]) -> None:
        """Verify columns included in composite indexes."""
        engine, _ = migrated_db
        async with engine.connect() as conn:
            # ix_user_wikis_lookup should cover (user_id, type, importance)
            lookup_res = await conn.execute(text("PRAGMA index_info('ix_user_wikis_lookup');"))
            lookup_cols = [str(r[2]) for r in lookup_res.fetchall()]
            assert lookup_cols == ["user_id", "type", "importance"]

            # ix_user_wikis_user_category should cover (user_id, category)
            user_cat_res = await conn.execute(text("PRAGMA index_info('ix_user_wikis_user_category');"))
            user_cat_cols = [str(r[2]) for r in user_cat_res.fetchall()]
            assert user_cat_cols == ["user_id", "category"]


class TestAlembicUniqueConstraintsEmpirical:
    """Empirically test unique constraints by attempting duplicate insertions."""

    @pytest.fixture
    async def session(self, tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
        db_file = tmp_path / "uq_test.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            engine = _create_engine_with_fk(db_url)
            session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_maker() as sess:
                yield sess
            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_uq_user_wikis_user_okf_id_enforcement(self, session: AsyncSession) -> None:
        """Verify uq_user_wikis_user_okf_id prevents duplicate okf_id for the same user, but allows across users."""
        u1 = User(id=str(uuid.uuid4()), username="user1", hashed_password="pw1")
        u2 = User(id=str(uuid.uuid4()), username="user2", hashed_password="pw2")
        session.add_all([u1, u2])
        await session.commit()

        # Add first wiki for user 1
        w1 = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u1.id,
            okf_id="concept_tars",
            title="TARS Architecture",
            tags=["ai", "robot"],
            relations={"related_to": []},
        )
        session.add(w1)
        await session.commit()

        # Add same okf_id for user 2 -> MUST SUCCEED (Multi-tenant)
        w2_user2 = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u2.id,
            okf_id="concept_tars",
            title="TARS Architecture for User 2",
            tags=["ai"],
            relations={"related_to": []},
        )
        session.add(w2_user2)
        await session.commit()

        # Add duplicate okf_id for user 1 -> MUST FAIL with IntegrityError
        w1_dup = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u1.id,
            okf_id="concept_tars",
            title="Duplicate TARS",
            tags=[],
            relations={},
        )
        session.add(w1_dup)
        with pytest.raises(IntegrityError):
            await session.commit()

        await session.rollback()

    @pytest.mark.asyncio
    async def test_uq_tars_settings_user_id_enforcement(self, session: AsyncSession) -> None:
        """Verify tars_settings allows only 1 settings record per user."""
        u = User(id=str(uuid.uuid4()), username="tars_user", hashed_password="pw")
        session.add(u)
        await session.commit()

        s1 = TARSSettings(id=str(uuid.uuid4()), user_id=u.id, humor_level=0.9, honesty_level=0.95)
        session.add(s1)
        await session.commit()

        s2 = TARSSettings(id=str(uuid.uuid4()), user_id=u.id, humor_level=0.5, honesty_level=0.5)
        session.add(s2)
        with pytest.raises(IntegrityError):
            await session.commit()

        await session.rollback()

    @pytest.mark.asyncio
    async def test_users_username_and_email_uniqueness(self, session: AsyncSession) -> None:
        """Verify username uniqueness and email uniqueness on users table."""
        u1 = User(id=str(uuid.uuid4()), username="alice", email="alice@tars.ai", hashed_password="pw1")
        session.add(u1)
        await session.commit()

        # Duplicate username
        u2 = User(id=str(uuid.uuid4()), username="alice", email="alice2@tars.ai", hashed_password="pw2")
        session.add(u2)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Duplicate email
        u3 = User(id=str(uuid.uuid4()), username="bob", email="alice@tars.ai", hashed_password="pw3")
        session.add(u3)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # Multiple users with NULL email allowed
        u4 = User(id=str(uuid.uuid4()), username="carol", email=None, hashed_password="pw4")
        u5 = User(id=str(uuid.uuid4()), username="dave", email=None, hashed_password="pw5")
        session.add_all([u4, u5])
        await session.commit()
        assert u4.id is not None and u5.id is not None


class TestAlembicForeignKeysAndCascades:
    """Empirically test Foreign Key constraints and CASCADE / SET NULL behaviors."""

    @pytest.fixture
    async def session(self, tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
        db_file = tmp_path / "fk_test.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            engine = _create_engine_with_fk(db_url)
            session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_maker() as sess:
                yield sess
            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_orphan_insert_rejection(self, session: AsyncSession) -> None:
        """Verify inserting records with non-existent user_id fails with IntegrityError."""
        fake_user_id = str(uuid.uuid4())

        # 1. Orphan TARSSettings
        s = TARSSettings(id=str(uuid.uuid4()), user_id=fake_user_id)
        session.add(s)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # 2. Orphan UserWikiIndex
        w = UserWikiIndex(id=str(uuid.uuid4()), user_id=fake_user_id, okf_id="concept_orphan", title="Orphan")
        session.add(w)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # 3. Orphan ChatSession
        cs = ChatSession(id=str(uuid.uuid4()), user_id=fake_user_id, title="Orphan Session")
        session.add(cs)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # 4. Orphan ChatMessage (valid session fake user, or fake session valid user)
        u = User(id=str(uuid.uuid4()), username="valid_user", hashed_password="pw")
        session.add(u)
        await session.commit()

        msg = ChatMessage(id=str(uuid.uuid4()), session_id=str(uuid.uuid4()), user_id=u.id, role="user", content="hello")
        session.add(msg)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    @pytest.mark.asyncio
    async def test_cascade_delete_user_removes_all_entities(self, session: AsyncSession) -> None:
        """Verify deleting a User cascades to TARSSettings, UserWikiIndex, ChatSession, and ChatMessage."""
        u = User(id=str(uuid.uuid4()), username="cascade_test", hashed_password="pw")
        session.add(u)
        await session.flush()

        settings = TARSSettings(id=str(uuid.uuid4()), user_id=u.id)
        wiki = UserWikiIndex(id=str(uuid.uuid4()), user_id=u.id, okf_id="rule_one", title="Rule One")
        session_obj = ChatSession(id=str(uuid.uuid4()), user_id=u.id, title="Dialogue 1")
        session.add_all([settings, wiki, session_obj])
        await session.flush()

        msg1 = ChatMessage(id=str(uuid.uuid4()), session_id=session_obj.id, user_id=u.id, role="user", content="hi")
        msg2 = ChatMessage(id=str(uuid.uuid4()), session_id=session_obj.id, user_id=u.id, role="assistant", content="hello")
        session.add_all([msg1, msg2])
        await session.commit()

        # Now delete User
        await session.delete(u)
        await session.commit()

        # Verify all dependent entities are gone
        res_s = await session.execute(select(TARSSettings).where(TARSSettings.user_id == u.id))
        assert res_s.scalar_one_or_none() is None

        res_w = await session.execute(select(UserWikiIndex).where(UserWikiIndex.user_id == u.id))
        assert len(res_w.scalars().all()) == 0

        res_cs = await session.execute(select(ChatSession).where(ChatSession.user_id == u.id))
        assert len(res_cs.scalars().all()) == 0

        res_m = await session.execute(select(ChatMessage).where(ChatMessage.user_id == u.id))
        assert len(res_m.scalars().all()) == 0

    @pytest.mark.asyncio
    async def test_session_parent_session_set_null_on_delete(self, session: AsyncSession) -> None:
        """Verify deleting parent ChatSession sets child session's parent_session_id to NULL in the database."""
        u = User(id=str(uuid.uuid4()), username="tree_user", hashed_password="pw")
        session.add(u)
        await session.flush()

        parent_sess = ChatSession(id=str(uuid.uuid4()), user_id=u.id, title="Parent Session")
        session.add(parent_sess)
        await session.flush()

        child_sess = ChatSession(
            id=str(uuid.uuid4()),
            user_id=u.id,
            title="Child Session",
            parent_session_id=parent_sess.id,
        )
        session.add(child_sess)
        await session.commit()

        # Delete parent session
        await session.delete(parent_sess)
        await session.commit()

        # Refresh child session from DB
        await session.refresh(child_sess)
        assert child_sess.parent_session_id is None


class TestAlembicORMOperationsAndAdversarialPayloads:
    """Stress-test ORM operations with extreme, adversarial, and complex data structures."""

    @pytest.fixture
    async def session(self, tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
        db_file = tmp_path / "orm_payload.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            engine = _create_engine_with_fk(db_url)
            session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_maker() as sess:
                yield sess
            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    @pytest.mark.asyncio
    async def test_adversarial_unicode_and_emojis(self, session: AsyncSession) -> None:
        """Persist and query complex Unicode, multi-byte emojis, mathematical symbols, and CJK characters."""
        emoji_username = "tars_🤖_🚀_99"
        u = User(id=str(uuid.uuid4()), username=emoji_username, hashed_password="pw")
        session.add(u)
        await session.commit()

        # Complex wiki with Korean, Japanese, Math symbols, emojis, and deep JSON
        complex_relations = {
            "depends_on": ["concept_quantum_🌐", "rule_⚡_alpha"],
            "metadata": {
                "math": "∫ f(x) dx = ∑ λ_i",
                "nested_levels": {"level_1": {"level_2": ["a", "b", "c"]}},
            },
        }
        w = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u.id,
            okf_id="concept_양자역학_🌌",
            title="양자 역학 & Relative Space-Time Relativity 🚀",
            category="과학/우주물리",
            tags=["양자", "relative", "🚀", "Ω_infinity"],
            relations=complex_relations,
            importance="critical",
        )
        session.add(w)
        await session.commit()

        # Query back and verify fidelity
        res = await session.execute(
            select(UserWikiIndex).where(
                UserWikiIndex.user_id == u.id,
                UserWikiIndex.okf_id == "concept_양자역학_🌌",
            )
        )
        fetched = res.scalar_one()
        assert fetched.title == "양자 역학 & Relative Space-Time Relativity 🚀"
        assert fetched.category == "과학/우주물리"
        assert fetched.tags == ["양자", "relative", "🚀", "Ω_infinity"]
        assert fetched.relations["metadata"]["math"] == "∫ f(x) dx = ∑ λ_i"
        assert fetched.relations["metadata"]["nested_levels"]["level_1"]["level_2"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_massive_payload_stress(self, session: AsyncSession) -> None:
        """Insert massive message content (50,000+ characters) and 500+ tags into migrated database."""
        u = User(id=str(uuid.uuid4()), username="stress_user", hashed_password="pw")
        session.add(u)
        await session.flush()

        sess = ChatSession(id=str(uuid.uuid4()), user_id=u.id, title="Massive Load Session")
        session.add(sess)
        await session.flush()

        # 50,000 characters message
        huge_text = "TARS-MASSIVE-TOKEN-CHUNK-" * 2000  # 50,000 chars
        msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=sess.id,
            user_id=u.id,
            role="assistant",
            content=huge_text,
            tokens=12500,
        )
        session.add(msg)

        # 500 tags wiki
        massive_tags = [f"tag_{i}_{uuid.uuid4().hex[:6]}" for i in range(500)]
        wiki = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u.id,
            okf_id="stress_tags_wiki",
            title="Massive Tags Wiki",
            tags=massive_tags,
            relations={"large_list": list(range(1000))},
        )
        session.add(wiki)
        await session.commit()

        # Query back
        res_msg = await session.execute(select(ChatMessage).where(ChatMessage.id == msg.id))
        fetched_msg = res_msg.scalar_one()
        assert len(fetched_msg.content) == len(huge_text)
        assert fetched_msg.tokens == 12500

        res_wiki = await session.execute(select(UserWikiIndex).where(UserWikiIndex.id == wiki.id))
        fetched_wiki = res_wiki.scalar_one()
        assert len(fetched_wiki.tags) == 500
        assert len(fetched_wiki.relations["large_list"]) == 1000

    @pytest.mark.asyncio
    async def test_composite_index_query_execution_plan(self, session: AsyncSession) -> None:
        """Verify that composite index queries execute and return filtered records correctly."""
        u = User(id=str(uuid.uuid4()), username="query_user", hashed_password="pw")
        session.add(u)
        await session.flush()

        # Create multiple wikis
        for i in range(10):
            imp = "critical" if i % 2 == 0 else "low"
            cat = "tech" if i < 5 else "personal"
            w = UserWikiIndex(
                id=str(uuid.uuid4()),
                user_id=u.id,
                okf_id=f"wiki_{i}",
                type="concept",
                title=f"Wiki {i}",
                category=cat,
                importance=imp,
            )
            session.add(w)
        await session.commit()

        # Query using ix_user_wikis_lookup (user_id, type, importance)
        stmt1 = select(UserWikiIndex).where(
            UserWikiIndex.user_id == u.id,
            UserWikiIndex.type == "concept",
            UserWikiIndex.importance == "critical",
        )
        res1 = await session.execute(stmt1)
        critical_concepts = res1.scalars().all()
        assert len(critical_concepts) == 5

        # Query using ix_user_wikis_user_category (user_id, category)
        stmt2 = select(UserWikiIndex).where(
            UserWikiIndex.user_id == u.id,
            UserWikiIndex.category == "tech",
        )
        res2 = await session.execute(stmt2)
        tech_wikis = res2.scalars().all()
        assert len(tech_wikis) == 5

    @pytest.mark.asyncio
    async def test_transaction_rollback_and_subsequent_operations(self, session: AsyncSession) -> None:
        """Verify transaction rollback recovery after an integrity violation allows normal subsequent transactions."""
        u_id = str(uuid.uuid4())
        u = User(id=u_id, username="tx_user", hashed_password="pw")
        session.add(u)
        await session.commit()

        # Cause IntegrityError with duplicate user_id for tars_settings
        s1 = TARSSettings(id=str(uuid.uuid4()), user_id=u_id)
        session.add(s1)
        await session.commit()

        s2 = TARSSettings(id=str(uuid.uuid4()), user_id=u_id)
        session.add(s2)
        with pytest.raises(IntegrityError):
            await session.commit()

        # Rollback
        await session.rollback()

        # Perform valid operation on same session
        w = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=u_id,
            okf_id="valid_after_rollback",
            title="Recovered Operation",
        )
        session.add(w)
        await session.commit()

        res = await session.execute(select(UserWikiIndex).where(UserWikiIndex.okf_id == "valid_after_rollback"))
        assert res.scalar_one().title == "Recovered Operation"


class TestHighConcurrencyAndEnvironment:
    """Stress-test concurrent read/write transactions and environment configuration."""

    @pytest.mark.asyncio
    async def test_concurrent_async_sessions_rw(self, tmp_path: Path) -> None:
        """Verify 20 concurrent tasks performing read/write operations on migrated database without corruption."""
        db_file = tmp_path / "concurrent_rw.db"
        db_url = f"sqlite+aiosqlite:///{db_file}"
        cfg = _build_alembic_config(db_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = db_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            engine = _create_engine_with_fk(db_url)
            session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async def _worker(worker_id: int) -> None:
                async with session_maker() as session:
                    user_id = str(uuid.uuid4())
                    u = User(id=user_id, username=f"worker_user_{worker_id}", hashed_password=f"pw_{worker_id}")
                    session.add(u)
                    await session.flush()

                    for j in range(3):
                        w = UserWikiIndex(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            okf_id=f"worker_{worker_id}_wiki_{j}",
                            title=f"Worker {worker_id} Doc {j}",
                        )
                        session.add(w)
                    await session.commit()

                    # Read back
                    res = await session.execute(select(UserWikiIndex).where(UserWikiIndex.user_id == user_id))
                    docs = res.scalars().all()
                    assert len(docs) == 3

            # Run 20 concurrent workers
            await asyncio.gather(*[_worker(i) for i in range(20)])

            # Verify total counts in DB
            async with session_maker() as session:
                res_u = await session.execute(select(User))
                users = res_u.scalars().all()
                assert len(users) == 20

                res_w = await session.execute(select(UserWikiIndex))
                wikis = res_w.scalars().all()
                assert len(wikis) == 60

            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)

    def test_run_migrations_script_executable(self) -> None:
        """Verify scripts/run_migrations.sh exists, is executable, and contains correct commands."""
        root = _get_project_root()
        script_path = root / "scripts" / "run_migrations.sh"
        assert script_path.is_file(), "scripts/run_migrations.sh missing"
        assert os.access(script_path, os.X_OK), "scripts/run_migrations.sh is not executable (+x)"

        content = script_path.read_text(encoding="utf-8")
        assert "alembic upgrade head" in content
        assert "uvicorn main:app" in content
        assert "TARS_DATABASE_URL" in content

    @pytest.mark.asyncio
    async def test_dynamic_url_override_via_alembic_execution(self, tmp_path: Path) -> None:
        """Verify that setting TARS_DATABASE_URL directs Alembic to target that specific database file."""
        custom_db = tmp_path / "custom_env_target.db"
        custom_url = f"sqlite+aiosqlite:///{custom_db}"
        cfg = _build_alembic_config(custom_url)

        orig_env = os.environ.get("TARS_DATABASE_URL")
        os.environ["TARS_DATABASE_URL"] = custom_url

        try:
            await asyncio.to_thread(command.upgrade, cfg, "head")
            assert custom_db.is_file(), "Alembic did not create target database from TARS_DATABASE_URL"

            # Check that custom_db has tables
            engine = create_async_engine(custom_url)
            async with engine.connect() as conn:
                res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
                tables = {str(r[0]) for r in res.fetchall()}
                assert "users" in tables
                assert "alembic_version" in tables
            await engine.dispose()
        finally:
            if orig_env is not None:
                os.environ["TARS_DATABASE_URL"] = orig_env
            else:
                os.environ.pop("TARS_DATABASE_URL", None)
