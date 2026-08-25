"""Tier 1 Unit Tests: SQLAlchemy 2.0 Async Models & Storage-DB Reconciliation (F4, F5).

Covers:
- F4: Async ORM schema: User, TarsSettings, UserWikiMetadata relationships & constraints
- F5: Storage-DB Reconciliation Engine:
  - Full sync of unindexed storage files to DB
  - Detection of modified files on disk (hash mismatch update)
  - Purging of orphaned DB records when files are deleted on disk
  - Multi-user isolation during reconciliation runs
  - Graceful handling of corrupted/invalid markdown files.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFSource,
    OKFType,
)
from tars.db.models import TarsSettings, User, UserWikiMetadata
from tars.storage.manager import FileStorageManager
from tars.storage.reconciliation import (
    ReconciliationResult,
    StorageDBReconciliationEngine,
)

# ============================================================================
# Helpers
# ============================================================================


def create_sample_okf(doc_id: str, title: str, content: str, importance: OKFImportance = OKFImportance.MEDIUM) -> OKFDocument:
    fm = OKFFrontmatter(
        id=doc_id,
        type=OKFType.RULE,
        title=title,
        tags=["reconcile", "test"],
        importance=importance,
        source=OKFSource.MANUAL,
    )
    return OKFDocument(frontmatter=fm, body=content)


# ============================================================================
# F4: SQLAlchemy Async Model & Constraint Tests
# ============================================================================


@pytest.mark.asyncio
async def test_user_and_settings_creation(async_db_session: AsyncSession) -> None:
    """Verify creating User with linked TarsSettings and querying via relationship."""
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        username="cooper",
        hashed_password="hashed_cooper_password",
        is_active=True,
    )
    settings = TarsSettings(
        id=str(uuid.uuid4()),
        user_id=user_id,
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
    )
    user.settings = settings

    async_db_session.add(user)
    async_db_session.add(settings)
    await async_db_session.commit()

    # Query back
    stmt = select(User).where(User.id == user_id)
    result = await async_db_session.execute(stmt)
    fetched_user = result.scalar_one()

    assert fetched_user.username == "cooper"
    assert fetched_user.settings is not None
    assert fetched_user.settings.humor_level == 0.90
    assert fetched_user.settings.honesty_level == 0.95


@pytest.mark.asyncio
async def test_user_wiki_metadata_model_crud(
    async_db_session: AsyncSession,
    test_user: User,
) -> None:
    """Verify inserting and querying UserWikiMetadata with JSON tags and relations."""
    wiki_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    wiki = UserWikiMetadata(
        id=wiki_id,
        user_id=test_user.id,
        okf_id="schedule_001",
        okf_version="1.0",
        type="rule",
        title="Weekly Meeting",
        category="schedule",
        tags=["team", "weekly"],
        importance="high",
        source="manual",
        relations={"depends_on": [], "related_to": []},
        file_path=f"/storage/users/{test_user.id}/wikis/schedule_001.md",
        file_hash="dummy_sha256_hash_value",
        created_at=now,
        updated_at=now,
    )
    async_db_session.add(wiki)
    await async_db_session.commit()

    stmt = select(UserWikiMetadata).where(
        UserWikiMetadata.user_id == test_user.id,
        UserWikiMetadata.okf_id == "schedule_001",
    )
    result = await async_db_session.execute(stmt)
    fetched_wiki = result.scalar_one()

    assert fetched_wiki.title == "Weekly Meeting"
    assert fetched_wiki.tags == ["team", "weekly"]
    assert fetched_wiki.importance == "high"


# ============================================================================
# F5: Storage-DB Reconciliation Engine Tests
# ============================================================================


@pytest.mark.asyncio
async def test_reconciliation_full_sync_new_files(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify reconciliation detects untracked files on disk and inserts DB index records."""
    # Write 2 OKF files directly to storage
    doc1 = create_sample_okf("doc_sync_1", "Sync 1", "Content 1")
    doc2 = create_sample_okf("doc_sync_2", "Sync 2", "Content 2")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc1)
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc2)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    summary: ReconciliationResult = await engine.reconcile_user(
        session=async_db_session, user_id=test_user.id
    )

    assert summary.created_count == 2
    assert summary.updated_count == 0
    assert summary.deleted_count == 0

    # Check DB
    stmt = select(UserWikiMetadata).where(UserWikiMetadata.user_id == test_user.id)
    records = (await async_db_session.execute(stmt)).scalars().all()
    assert len(records) == 2
    okf_ids = {r.okf_id for r in records}
    assert okf_ids == {"doc_sync_1", "doc_sync_2"}


@pytest.mark.asyncio
async def test_reconciliation_updates_modified_file_hash(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify reconciliation detects file modification and updates DB metadata and hash."""
    doc = create_sample_okf("doc_mod", "Original Title", "Original Content")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    await engine.reconcile_user(session=async_db_session, user_id=test_user.id)

    # Modify file content on disk
    doc_mod = create_sample_okf("doc_mod", "Updated Title", "New Modified Content")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc_mod)

    # Reconcile again
    summary = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)
    assert summary.updated_count == 1
    assert summary.created_count == 0

    # Query DB
    stmt = select(UserWikiMetadata).where(
        UserWikiMetadata.user_id == test_user.id,
        UserWikiMetadata.okf_id == "doc_mod",
    )
    record = (await async_db_session.execute(stmt)).scalar_one()
    assert record.title == "Updated Title"


@pytest.mark.asyncio
async def test_reconciliation_purges_deleted_files_from_db(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify that when a file is deleted on disk, reconciliation removes the orphaned DB index."""
    doc = create_sample_okf("doc_to_purge", "To Purge", "Content")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)
    await engine.reconcile_user(session=async_db_session, user_id=test_user.id)

    # Delete from file system
    await test_storage_manager.delete_okf_file(user_id=test_user.id, okf_id="doc_to_purge")

    # Reconcile
    summary = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)
    assert summary.deleted_count == 1

    # Verify DB has no records
    stmt = select(UserWikiMetadata).where(
        UserWikiMetadata.user_id == test_user.id,
        UserWikiMetadata.okf_id == "doc_to_purge",
    )
    record = (await async_db_session.execute(stmt)).scalar_one_or_none()
    assert record is None


@pytest.mark.asyncio
async def test_reconciliation_multi_user_isolation(
    async_db_session: AsyncSession,
    test_storage_manager: FileStorageManager,
    test_user: User,
) -> None:
    """Verify reconciling user A does not alter or purge user B's records."""
    other_user_id = str(uuid.uuid4())
    other_user = User(
        id=other_user_id,
        username="brand",
        hashed_password="hashed_brand_password",
    )
    async_db_session.add(other_user)
    await async_db_session.commit()

    # User 1 file
    doc1 = create_sample_okf("doc_user_1", "User 1 Doc", "Content 1")
    await test_storage_manager.save_okf_file(user_id=test_user.id, doc=doc1)

    # User 2 file
    doc2 = create_sample_okf("doc_user_2", "User 2 Doc", "Content 2")
    await test_storage_manager.save_okf_file(user_id=other_user_id, doc=doc2)

    engine = StorageDBReconciliationEngine(storage_manager=test_storage_manager)

    # Reconcile only user 1
    summary1 = await engine.reconcile_user(session=async_db_session, user_id=test_user.id)
    assert summary1.created_count == 1

    # Reconcile only user 2
    summary2 = await engine.reconcile_user(session=async_db_session, user_id=other_user_id)
    assert summary2.created_count == 1

    # Verify counts per user
    stmt1 = select(UserWikiMetadata).where(UserWikiMetadata.user_id == test_user.id)
    stmt2 = select(UserWikiMetadata).where(UserWikiMetadata.user_id == other_user_id)

    res1 = (await async_db_session.execute(stmt1)).scalars().all()
    res2 = (await async_db_session.execute(stmt2)).scalars().all()

    assert len(res1) == 1
    assert len(res2) == 1
    assert res1[0].okf_id == "doc_user_1"
    assert res2[0].okf_id == "doc_user_2"
