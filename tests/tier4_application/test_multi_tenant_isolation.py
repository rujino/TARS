"""Tier 4 Application Tests: Multi-Tenant Data Isolation & Path Traversal Security.

Verifies:
1. File Storage Layer Isolation:
   - User A (Cooper) and User B (Brand) have separate directory roots:
     /storage/users/{user_id}/wikis/*.md
   - User B cannot list, read, or delete User A's OKF files.
2. Path Traversal Guard:
   - Malicious okf_id strings containing directory traversal patterns (e.g., `../../user_a/wikis/secret.md`,
     `../..//etc/passwd`, `/absolute/path`) are blocked and raise security exceptions.
3. Database Query Isolation:
   - RDBMS UserWikiIndex records are partitioned strictly by `user_id`.
   - Index queries for User B never leak or return User A's indexed documents.
4. Dynamic Slicer Multi-Tenant Isolation:
   - Slicing context for User B with matching search terms never retrieves User A's documents.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.db.models import User, UserWikiIndex
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager, StoragePathTraversalError

# ============================================================================
# Helper to create test OKF documents
# ============================================================================


def create_test_okf(doc_id: str, title: str, content: str) -> OKFDocument:
    now = datetime.now(UTC)
    return OKFDocument(
        metadata=OKFMetadata(
            okf_version="1.0",
            id=doc_id,
            type=OKFType.CONCEPT,
            title=title,
            category="confidential",
            tags=["mission", "classified"],
            importance=OKFImportance.CRITICAL,
            source=OKFSource.MANUAL,
            relations=OKFRelations(depends_on=[], related_to=[]),
            created_at=now,
            updated_at=now,
        ),
        content=content,
    )


# ============================================================================
# 1. Storage Layer Multi-Tenant Isolation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_storage_manager_user_isolation(
    storage_manager: FileStorageManager,
    seed_test_user: User,
    seed_second_user: User,
) -> None:
    """Verify that User A and User B cannot see each other's files on disk."""
    user_a_id = seed_test_user.id
    user_b_id = seed_second_user.id

    # 1. User A saves a confidential file
    doc_a = create_test_okf(
        doc_id="classified_plan_a",
        title="Gargantua Descent Coordinates",
        content="Coordinates: [89.4, -12.3, 44.1]. Top secret mission data.",
    )
    await storage_manager.save_okf_file(user_id=user_a_id, doc=doc_a)

    # 2. User B saves a research file
    doc_b = create_test_okf(
        doc_id="edmunds_data_b",
        title="Edmunds Planet Atmospheric Data",
        content="Atmosphere contains breathable oxygen (21%).",
    )
    await storage_manager.save_okf_file(user_id=user_b_id, doc=doc_b)

    # 3. User A lists files -> must see only doc_a
    files_a = await storage_manager.list_okf_files(user_id=user_a_id)
    ids_a = [f.metadata.id for f in files_a]
    assert "classified_plan_a" in ids_a
    assert "edmunds_data_b" not in ids_a

    # 4. User B lists files -> must see only doc_b
    files_b = await storage_manager.list_okf_files(user_id=user_b_id)
    ids_b = [f.metadata.id for f in files_b]
    assert "edmunds_data_b" in ids_b
    assert "classified_plan_a" not in ids_b

    # 5. User B tries to read User A's file directly by ID -> returns None or raises FileNotFoundError
    with pytest.raises((FileNotFoundError, KeyError)):
        await storage_manager.read_okf_file(user_id=user_b_id, okf_id="classified_plan_a")


# ============================================================================
# 2. Path Traversal Security Tests
# ============================================================================


@pytest.mark.asyncio
async def test_storage_manager_blocks_path_traversal_attacks(
    storage_manager: FileStorageManager,
    seed_second_user: User,
) -> None:
    """Verify malicious path traversal attempts in okf_id are strictly rejected."""
    user_b_id = seed_second_user.id

    malicious_ids = [
        "../../user_test_alpha/wikis/classified_plan_a",
        "../secret",
        "../../../etc/passwd",
        "/etc/shadow",
        "nested/../../secret",
        "~/.ssh/id_rsa",
        "null\x00escape",
    ]

    for attack_id in malicious_ids:
        # Read attempt
        with pytest.raises((StoragePathTraversalError, ValueError, FileNotFoundError)):
            await storage_manager.read_okf_file(user_id=user_b_id, okf_id=attack_id)

        # Save attempt
        with pytest.raises((StoragePathTraversalError, ValueError)):
            attack_doc = create_test_okf(
                doc_id=attack_id,
                title="Attack Document",
                content="Malicious payload",
            )
            await storage_manager.save_okf_file(user_id=user_b_id, doc=attack_doc)

        # Delete attempt
        with pytest.raises((StoragePathTraversalError, ValueError, FileNotFoundError)):
            await storage_manager.delete_okf_file(user_id=user_b_id, okf_id=attack_id)


# ============================================================================
# 3. Database Metadata Index Isolation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_db_user_wikis_index_isolation(
    db_session: AsyncSession,
    seed_test_user: User,
    seed_second_user: User,
) -> None:
    """Verify DB index queries are strictly scoped by user_id."""
    user_a_id = seed_test_user.id
    user_b_id = seed_second_user.id

    # Seed DB records for User A and User B
    entry_a = UserWikiIndex(
        id="index_a_001",
        user_id=user_a_id,
        okf_id="plan_a",
        file_path=f"storage/users/{user_a_id}/wikis/plan_a.md",
        title="Plan A",
        doc_type="concept",
        category="secret",
        importance="critical",
        tags="['secret', 'plan']",
        file_hash="hash_a",
    )
    entry_b = UserWikiIndex(
        id="index_b_001",
        user_id=user_b_id,
        okf_id="plan_b",
        file_path=f"storage/users/{user_b_id}/wikis/plan_b.md",
        title="Plan B",
        doc_type="concept",
        category="research",
        importance="high",
        tags="['research', 'planet']",
        file_hash="hash_b",
    )
    db_session.add_all([entry_a, entry_b])
    await db_session.commit()

    # Query for User B
    stmt_b = select(UserWikiIndex).where(UserWikiIndex.user_id == user_b_id)
    result_b = await db_session.execute(stmt_b)
    rows_b = result_b.scalars().all()

    assert len(rows_b) == 1
    assert rows_b[0].okf_id == "plan_b"
    assert rows_b[0].user_id == user_b_id


# ============================================================================
# 4. Dynamic Slicer Multi-Tenant Isolation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_dynamic_slicer_never_leaks_cross_tenant_wikis(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
    seed_test_user: User,
    seed_second_user: User,
) -> None:
    """Verify DynamicSlicerEngine only returns documents belonging to the requesting user."""
    user_a_id = seed_test_user.id
    user_b_id = seed_second_user.id

    # User A creates a document about "gravitational anomaly"
    doc_a = create_test_okf(
        doc_id="gravity_anomaly_a",
        title="Gravitational Anomaly in Sector 4",
        content="Detected severe gravitational distortion near Saturn.",
    )
    await storage_manager.save_okf_file(user_id=user_a_id, doc=doc_a)

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    # User B queries specifically for "gravitational anomaly"
    slices_for_user_b = await slicer.slice_context(
        user_id=user_b_id,
        query="Tell me about the gravitational anomaly near Saturn.",
        token_budget=1500,
    )

    # Must return 0 documents because User A owns it
    assert len(slices_for_user_b) == 0

    # User A queries the same thing -> should retrieve it
    slices_for_user_a = await slicer.slice_context(
        user_id=user_a_id,
        query="Tell me about the gravitational anomaly near Saturn.",
        token_budget=1500,
    )
    assert len(slices_for_user_a) == 1
    assert slices_for_user_a[0].metadata.id == "gravity_anomaly_a"
