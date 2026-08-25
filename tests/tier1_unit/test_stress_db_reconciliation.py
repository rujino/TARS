"""Tier 1 Adversarial & Stress Tests: Database Models, Multi-Tenant Isolation & Reconciliation Engine.

Challenger 2 Empirical Verification Suite:
1. Out-of-sync states (OOB additions, disk deletions, DB orphans, hash mismatches, corrupted files, dry-run audit)
2. Multi-tenant isolation (cross-user collisions, path traversal, concurrent reconciliations, foreign key cascading)
3. Transaction rollback & atomicity on failures
4. Data integrity, JSON relations, and UTC datetime handling
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.core.okf.serializer import serialize_okf_document
from tars.db.base import Base
from tars.db.models import (
    TARSSettings,
    User,
    UserWikiIndex,
)
from tars.db.session import _enable_sqlite_foreign_keys, get_db
from tars.storage.manager import (
    FileStorageManager,
    StoragePathTraversalError,
    StorageSecurityError,
)
from tars.storage.reconciliation import (
    ReconciliationResult,
    StorageDBReconciliationEngine,
)

# ============================================================================
# Helper Factories
# ============================================================================


def make_doc(
    doc_id: str,
    title: str = "Test Doc",
    body: str = "Sample content body",
    doc_type: OKFType = OKFType.CONCEPT,
    importance: OKFImportance = OKFImportance.MEDIUM,
    tags: list[str] | None = None,
    relations: OKFRelations | None = None,
    category: str | None = "general",
) -> OKFDocument:
    fm = OKFFrontmatter(
        okf_version="1.0",
        id=doc_id,
        type=doc_type,
        title=title,
        category=category,
        tags=tags or ["test", "stress"],
        importance=importance,
        source=OKFSource.MANUAL,
        relations=relations or OKFRelations(depends_on=[], related_to=[]),
        created_at=datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC),
    )
    return OKFDocument(metadata=fm, content=body)


# ============================================================================
# 1. OUT-OF-SYNC STATES & EDGE CASE STRESS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_reconciliation_out_of_band_disk_addition(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Empirically test out-of-band files directly placed on disk without storage API."""
    user_dir = test_storage_manager.get_user_wikis_dir(test_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # 3 files written directly via raw file I/O
    for i in range(1, 4):
        raw_md = f"""---
okf_version: "1.0"
id: "oob_doc_{i}"
type: "procedure"
title: "OOB Procedure {i}"
category: "ops"
tags:
  - "oob"
  - "manual"
importance: "high"
source: "manual"
relations:
  depends_on: []
  related_to: []
created_at: "2026-08-20T10:00:00Z"
updated_at: "2026-08-20T10:00:00Z"
---

# OOB Procedure {i}
Direct disk write test content.
"""
        (user_dir / f"oob_doc_{i}.md").write_text(raw_md, encoding="utf-8")

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    result = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)

    assert result.is_clean
    assert result.scanned_files_count == 3
    assert result.created_count == 3
    assert result.inserted_count == 3
    assert result.updated_count == 0
    assert result.deleted_count == 0

    # Query DB to verify all records exist with exact hashes
    records = (
        (
            await async_db_session.execute(
                select(UserWikiIndex).where(UserWikiIndex.user_id == test_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(records) == 3
    record_map = {r.okf_id: r for r in records}
    assert "oob_doc_1" in record_map
    assert record_map["oob_doc_1"].title == "OOB Procedure 1"
    assert record_map["oob_doc_1"].type == "procedure"
    assert record_map["oob_doc_1"].importance == "high"


@pytest.mark.asyncio
async def test_reconciliation_hash_mismatch_and_body_mutation(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify that changing markdown body on disk updates hash and metadata in DB."""
    doc = make_doc(
        "mod_doc_01",
        title="Original Title",
        body="Original Body Line 1\n--- Horizontal line\nLine 2",
    )
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    res1 = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)
    assert res1.created_count == 1

    # Record original hash from DB
    rec1 = (
        await async_db_session.execute(
            select(UserWikiIndex).where(
                UserWikiIndex.user_id == test_user.id, UserWikiIndex.okf_id == "mod_doc_01"
            )
        )
    ).scalar_one()
    orig_hash = rec1.file_hash

    # Modify body directly on disk
    user_dir = test_storage_manager.get_user_wikis_dir(test_user.id)
    new_raw = """---
okf_version: "1.0"
id: "mod_doc_01"
type: "concept"
title: "Mutated Title"
category: "general"
tags:
  - "mutated"
importance: "critical"
source: "manual"
relations:
  depends_on:
    - "dep_01"
  related_to: []
created_at: "2026-08-20T12:00:00Z"
updated_at: "2026-08-23T15:30:00Z"
---

# Mutated Title
This body has been heavily altered!
"""
    (user_dir / "mod_doc_01.md").write_text(new_raw, encoding="utf-8")

    # Reconcile again
    res2 = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)
    assert res2.is_clean
    assert res2.updated_count == 1
    assert res2.created_count == 0
    assert res2.deleted_count == 0

    # Query DB and check updated values
    await async_db_session.refresh(rec1)
    assert rec1.file_hash != orig_hash
    assert rec1.title == "Mutated Title"
    assert rec1.importance == "critical"
    assert rec1.tags == ["mutated"]
    assert rec1.relations == {"depends_on": ["dep_01"], "related_to": []}


@pytest.mark.asyncio
async def test_reconciliation_corrupted_files_and_graceful_fault_tolerance(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Stress-test reconciliation when directory contains corrupted, unparseable, and junk files."""
    user_dir = test_storage_manager.get_user_wikis_dir(test_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # 1. Valid file
    valid_doc = make_doc("valid_doc", title="Valid Doc", body="I am completely valid.")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=valid_doc)

    # 2. Corrupt YAML frontmatter
    (user_dir / "corrupt_yaml.md").write_text(
        "---\nid: corrupt_yaml\ntitle: [Unclosed list\n---\nBody content",
        encoding="utf-8",
    )

    # 3. Missing required frontmatter fields (missing type, id)
    (user_dir / "missing_fields.md").write_text(
        "---\ntitle: Only Title\n---\nBody content",
        encoding="utf-8",
    )

    # 4. Completely non-frontmatter text
    (user_dir / "plain_text.md").write_text(
        "Just a plain markdown text without frontmatter delimiters at all.",
        encoding="utf-8",
    )

    # 5. Non-markdown file (should be ignored by *.md glob)
    (user_dir / "notes.txt").write_text("Should be ignored.", encoding="utf-8")

    # 6. Hidden temp file (starts with .)
    (user_dir / ".tmp.draft.md").write_text(
        "Should be skipped by hidden file filter.", encoding="utf-8"
    )

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    result = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)

    # Scanned valid files should be 1, but errors list should capture the 3 invalid .md files
    assert result.scanned_files_count == 1
    assert result.created_count == 1
    assert len(result.errors) == 3
    assert not result.is_clean

    # Valid doc must be in DB
    records = (
        (
            await async_db_session.execute(
                select(UserWikiIndex).where(UserWikiIndex.user_id == test_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(records) == 1
    assert records[0].okf_id == "valid_doc"


@pytest.mark.asyncio
async def test_verify_user_integrity_dry_run_audit(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Test verify_user_integrity dry-run audit for MISSING_IN_DB, MISSING_IN_STORAGE, HASH_MISMATCH."""
    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)

    # Setup:
    # 1. doc_both_synced (exists on disk and in DB with matching hash)
    # 2. doc_disk_only (exists on disk, missing in DB -> MISSING_IN_DB)
    # 3. doc_db_only (exists in DB, missing on disk -> MISSING_IN_STORAGE)
    # 4. doc_hash_mismatch (exists in both, but disk content modified -> HASH_MISMATCH)

    doc_synced = make_doc("doc_synced", "Synced Doc")
    doc_disk_only = make_doc("doc_disk_only", "Disk Only Doc")
    doc_mismatch = make_doc("doc_mismatch", "Mismatch Doc", body="Original body")

    await test_storage_manager.save_okf_file(test_user.id, doc_synced)
    await test_storage_manager.save_okf_file(test_user.id, doc_mismatch)

    # Initial sync for synced and mismatch
    await engine.reconcile_user(session=async_db_session, user_id=test_user.id)

    # Now add doc_disk_only to disk
    await test_storage_manager.save_okf_file(test_user.id, doc_disk_only)

    # Now add doc_db_only directly to DB
    db_only_rec = UserWikiIndex(
        user_id=test_user.id,
        okf_id="doc_db_only",
        okf_version="1.0",
        type="concept",
        title="DB Only Doc",
        category="general",
        tags=["orphan"],
        importance="medium",
        source="manual",
        relations={"depends_on": [], "related_to": []},
        file_path=f"/storage/users/{test_user.id}/wikis/doc_db_only.md",
        file_hash="fake_hash_12345",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async_db_session.add(db_only_rec)
    await async_db_session.flush()

    # Mutate doc_mismatch on disk
    user_dir = test_storage_manager.get_user_wikis_dir(test_user.id)
    mutated_doc_mismatch = make_doc("doc_mismatch", "Mismatch Doc", body="MODIFIED BODY TEXT")
    (user_dir / "doc_mismatch.md").write_text(
        serialize_okf_document(mutated_doc_mismatch), encoding="utf-8"
    )

    # Run dry-run audit
    violations = await engine.verify_user_integrity(user_id=test_user.id, session=async_db_session)
    assert len(violations) == 3

    v_map = {v.okf_id: v for v in violations}
    assert "doc_disk_only" in v_map
    assert v_map["doc_disk_only"].violation_type == "MISSING_IN_DB"

    assert "doc_db_only" in v_map
    assert v_map["doc_db_only"].violation_type == "MISSING_IN_STORAGE"

    assert "doc_mismatch" in v_map
    assert v_map["doc_mismatch"].violation_type == "HASH_MISMATCH"

    # Verify dry-run did NOT change DB state
    db_records_after = (
        (
            await async_db_session.execute(
                select(UserWikiIndex).where(UserWikiIndex.user_id == test_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(db_records_after) == 3  # synced, mismatch, db_only


# ============================================================================
# 2. MULTI-TENANT ISOLATION & SECURITY STRESS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_multi_tenant_same_okf_id_collision(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
) -> None:
    """Verify multiple users can have the identical okf_id without collision."""
    # Create 3 users
    users = []
    for i in range(1, 4):
        u = User(id=str(uuid.uuid4()), username=f"tenant_user_{i}", hashed_password="pwd")
        users.append(u)
        async_db_session.add(u)
    await async_db_session.commit()

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)

    # Save document with SAME okf_id 'common_guide' for all 3 users with different titles
    for i, u in enumerate(users, 1):
        doc = make_doc(
            "common_guide", title=f"User {i} Custom Guide", body=f"Private notes for user {i}"
        )
        await test_storage_manager.save_okf_file(user_id=u.id, doc=doc)
        res = await engine.reconcile_user(session=async_db_session, user_id=u.id)
        assert res.created_count == 1

    # Verify DB has 3 distinct records with identical okf_id
    stmt = select(UserWikiIndex).where(UserWikiIndex.okf_id == "common_guide")
    records = (await async_db_session.execute(stmt)).scalars().all()
    assert len(records) == 3
    found_user_ids = {r.user_id for r in records}
    assert found_user_ids == {u.id for u in users}

    # Verify file contents are strictly segregated
    for i, u in enumerate(users, 1):
        read_doc = await test_storage_manager.read_okf_file(user_id=u.id, okf_id="common_guide")
        assert read_doc.metadata.title == f"User {i} Custom Guide"
        assert f"Private notes for user {i}" in read_doc.body


@pytest.mark.asyncio
async def test_path_traversal_adversarial_reconciliation(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
) -> None:
    """Test malicious user_id and okf_id inputs attempting directory traversal."""
    malicious_ids = [
        "../traversal",
        "../../etc/passwd",
        "user_1/../user_2",
        "user\0nullbyte",
        "user/slash",
        "user\\backslash",
        "user with spaces",
        "user#hash",
        "a" * 129,  # exceeds 128 chars limit
    ]

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)

    for bad_id in malicious_ids:
        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            test_storage_manager.get_user_wikis_dir(bad_id)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            test_storage_manager.get_file_path(bad_id, "normal_okf")

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            test_storage_manager.get_file_path("normal_user", bad_id)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await engine.reconcile_user(session=async_db_session, user_id=bad_id)


@pytest.mark.asyncio
async def test_sqlite_foreign_key_cascade_deletion() -> None:
    """Verify SQLite foreign key cascade: deleting a User purges TARSSettings & UserWikiIndex when FKs are enabled."""
    from sqlalchemy import event
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
        future=True,
    )
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    user_id = str(uuid.uuid4())
    async with session_factory() as session:
        user = User(id=user_id, username="cooper", hashed_password="pwd")
        settings = TARSSettings(
            id=str(uuid.uuid4()),
            user_id=user_id,
            humor_level=0.9,
            honesty_level=0.95,
            mode="companion",
        )
        wiki = UserWikiIndex(
            id=str(uuid.uuid4()),
            user_id=user_id,
            okf_id="wiki_cascade_test",
            okf_version="1.0",
            type="concept",
            title="Cascade Test",
            category="ops",
            tags=["cascade"],
            importance="low",
            source="manual",
            relations={"depends_on": [], "related_to": []},
            file_path="/dummy/path.md",
            file_hash="hash123",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add_all([user, settings, wiki])
        await session.commit()

    # Verify records exist before delete
    async with session_factory() as session:
        w_before = (
            (await session.execute(select(UserWikiIndex).where(UserWikiIndex.user_id == user_id)))
            .scalars()
            .all()
        )
        s_before = (
            (await session.execute(select(TARSSettings).where(TARSSettings.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(w_before) == 1
        assert len(s_before) == 1

        # Delete User
        u_fetched = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        await session.delete(u_fetched)
        await session.commit()

    # Verify orphaned records are automatically cascaded in DB
    async with session_factory() as session:
        w_after = (
            (await session.execute(select(UserWikiIndex).where(UserWikiIndex.user_id == user_id)))
            .scalars()
            .all()
        )
        s_after = (
            (await session.execute(select(TARSSettings).where(TARSSettings.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(w_after) == 0
        assert len(s_after) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_multi_user_reconciliation_stress(
    test_storage_manager: FileStorageManager,
    tmp_path: Path,
) -> None:
    """Stress-test 10 distinct users running concurrent reconciliation in parallel sessions."""
    from sqlalchemy import event

    db_path = tmp_path / "concurrent_stress.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        future=True,
    )
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    num_users = 10
    docs_per_user = 5
    user_ids = [str(uuid.uuid4()) for _ in range(num_users)]

    # 1. Create all users in a dedicated session
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as setup_session:
        for u_id in user_ids:
            u = User(id=u_id, username=f"concurrent_{u_id[:8]}", hashed_password="pwd")
            setup_session.add(u)
        await setup_session.commit()

    # 2. Write 5 docs for each user to disk
    for u_id in user_ids:
        for d_idx in range(docs_per_user):
            doc = make_doc(
                f"doc_{d_idx}",
                title=f"User {u_id[:6]} Doc {d_idx}",
                body=f"Content for user {u_id} doc {d_idx}",
            )
            await test_storage_manager.save_okf_file(user_id=u_id, doc=doc)

    # 3. Concurrently run reconcile_user across separate async sessions
    async def reconcile_worker(uid: str) -> ReconciliationResult:
        async with session_factory() as sess:
            reconciler = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
            res = await reconciler.reconcile_user(session=sess, user_id=uid)
            await sess.commit()
            return res

    tasks = [reconcile_worker(uid) for uid in user_ids]
    results = await asyncio.gather(*tasks)

    # Verify all succeeded with clean results
    assert len(results) == num_users
    for res in results:
        assert res.is_clean
        assert res.created_count == docs_per_user
        assert res.scanned_files_count == docs_per_user

    # 4. Verify total DB count is exactly num_users * docs_per_user
    async with session_factory() as check_session:
        all_wikis = (await check_session.execute(select(UserWikiIndex))).scalars().all()
        assert len(all_wikis) == num_users * docs_per_user

    await engine.dispose()


# ============================================================================
# 3. TRANSACTION ROLLBACK & ATOMICITY TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_reconciliation_transaction_rollback_on_session_error(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify that if an error happens before commit, rolling back session preserves pre-state."""
    user_id = test_user.id
    doc1 = make_doc("doc_rollback_1", "Doc 1")
    await test_storage_manager.save_okf_file(user_id=user_id, doc=doc1)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    # Stage reconciliation (flushes, does not commit)
    res = await engine.reconcile_user(session=async_db_session, user_id=user_id)
    assert res.created_count == 1

    # Simulate an intentional failure and rollback
    await async_db_session.rollback()

    # Verify nothing was committed to DB
    records = (
        (
            await async_db_session.execute(
                select(UserWikiIndex).where(UserWikiIndex.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(records) == 0
    assert len(records) == 0


@pytest.mark.asyncio
async def test_get_db_fastapi_dependency_rollback_on_exception(
    test_engine: AsyncEngine,
    test_user: User,
) -> None:
    """Verify FastAPI get_db dependency automatically rolls back when an exception escapes."""
    import tars.db.session as session_module

    # Monkeypatch singleton sessionmaker to use our test engine
    custom_sessionmaker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    session_module._sessionmaker = custom_sessionmaker

    # Generator test: simulate yielding session and raising exception
    generator = get_db()
    session = await anext(generator)

    # Insert a wiki record
    wiki = UserWikiIndex(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        okf_id="should_rollback",
        okf_version="1.0",
        type="rule",
        title="To Rollback",
        tags=[],
        importance="medium",
        source="manual",
        relations={"depends_on": [], "related_to": []},
        file_path="/dummy/path.md",
        file_hash="hash",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(wiki)

    # Throw exception into generator to simulate HTTP error during request
    with pytest.raises(RuntimeError, match="Simulated HTTP 500 handler crash"):
        await generator.athrow(RuntimeError("Simulated HTTP 500 handler crash"))

    # Verify record was rolled back
    async with custom_sessionmaker() as verify_sess:
        rec = (
            await verify_sess.execute(
                select(UserWikiIndex).where(UserWikiIndex.okf_id == "should_rollback")
            )
        ).scalar_one_or_none()
        assert rec is None


# ============================================================================
# 4. SINGLE DOCUMENT FAST SYNC & DELETION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_sync_single_document_and_delete_fast_path(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify sync_single_document and delete_single_document_metadata fast path helpers."""
    doc = make_doc(
        "single_fast_doc",
        title="Fast Sync Doc",
        tags=["fast", "sync"],
        relations=OKFRelations(depends_on=["parent_01"], related_to=["sibling_01"]),
    )
    path = await test_storage_manager.save_okf_file(test_user.id, doc)
    file_hash = await test_storage_manager.get_file_hash(test_user.id, "single_fast_doc")

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)

    # 1. Fast sync insert
    record = await engine.sync_single_document(
        user_id=test_user.id,
        doc=doc,
        file_path=path,
        file_hash=file_hash,
        session=async_db_session,
    )
    assert record.okf_id == "single_fast_doc"
    assert record.title == "Fast Sync Doc"
    assert record.relations == {"depends_on": ["parent_01"], "related_to": ["sibling_01"]}

    # 2. Fast sync update
    doc_updated = make_doc(
        "single_fast_doc",
        title="Updated Fast Sync Doc",
        tags=["fast", "sync", "v2"],
    )
    record_updated = await engine.sync_single_document(
        user_id=test_user.id,
        doc=doc_updated,
        file_path=path,
        file_hash="new_hash_value",
        session=async_db_session,
    )
    assert record_updated.title == "Updated Fast Sync Doc"
    assert record_updated.tags == ["fast", "sync", "v2"]
    assert record_updated.file_hash == "new_hash_value"

    # 3. Fast deletion
    deleted = await engine.delete_single_document_metadata(
        user_id=test_user.id,
        okf_id="single_fast_doc",
        session=async_db_session,
    )
    assert deleted is True

    # 4. Deleting non-existent returns False
    deleted_again = await engine.delete_single_document_metadata(
        user_id=test_user.id,
        okf_id="single_fast_doc",
        session=async_db_session,
    )
    assert deleted_again is False


# ============================================================================
# 5. DATA TYPES & ORM CONSTRAINTS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_unique_constraint_violation_user_okf_id(
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """Verify that inserting duplicate (user_id, okf_id) raises IntegrityError."""
    wiki1 = UserWikiIndex(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        okf_id="duplicate_key_doc",
        okf_version="1.0",
        type="rule",
        title="Doc 1",
        tags=[],
        importance="medium",
        source="manual",
        relations={"depends_on": [], "related_to": []},
        file_path="/dummy/path1.md",
        file_hash="hash1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    wiki2 = UserWikiIndex(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        okf_id="duplicate_key_doc",
        okf_version="1.0",
        type="rule",
        title="Doc 2",
        tags=[],
        importance="medium",
        source="manual",
        relations={"depends_on": [], "related_to": []},
        file_path="/dummy/path2.md",
        file_hash="hash2",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async_db_session.add(wiki1)
    await async_db_session.flush()

    async_db_session.add(wiki2)
    with pytest.raises(IntegrityError):
        await async_db_session.flush()

    await async_db_session.rollback()
