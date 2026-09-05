"""Tier 1 Unit Tests: Dynamic Prompt Slicer Engine Parallel Batch OKF Reads (PERF-01)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.db.models import UserWikiIndex
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager


def make_okf_doc(
    doc_id: str,
    title: str,
    body: str = "Test document content.",
    doc_type: OKFType = OKFType.CONCEPT,
    importance: OKFImportance = OKFImportance.MEDIUM,
    tags: list[str] | None = None,
) -> OKFDocument:
    """Helper to build a valid OKFDocument for slicer testing."""
    now = datetime.now(UTC)
    metadata = OKFMetadata(
        id=doc_id,
        type=doc_type,
        title=title,
        category="testing",
        tags=tags or ["unit_test"],
        importance=importance,
        source=OKFSource.MANUAL,
        relations=OKFRelations(),
        created_at=now,
        updated_at=now,
    )
    return OKFDocument(metadata=metadata, content=body)


@pytest.mark.asyncio
async def test_slicer_parallel_batch_fetch(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify _fetch_via_db concurrently loads multiple candidate files via asyncio.gather."""
    user_id = "test_user_parallel_01"
    doc_ids = [f"doc_concurrent_{i}" for i in range(5)]

    # 1. Save 5 documents in file storage and DB index
    for okf_id in doc_ids:
        doc = make_okf_doc(doc_id=okf_id, title=f"Title for {okf_id}")
        await storage_manager.save_okf_file(user_id=user_id, doc=doc)

        record = UserWikiIndex(
            user_id=user_id,
            okf_id=okf_id,
            title=f"Title for {okf_id}",
            type="concept",
            category="testing",
            importance="medium",
            tags=["unit_test"],
            file_path=f"storage/users/{user_id}/wikis/{okf_id}.md",
        )
        db_session.add(record)

    await db_session.commit()

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    # 2. Spy on asyncio.gather to confirm batch execution
    with patch("asyncio.gather", wraps=__import__("asyncio").gather) as spy_gather:
        fetched_docs = await slicer._fetch_via_db(
            user_id=user_id,
            db_session=db_session,
            candidate_limit=25,
        )

        assert spy_gather.called
        assert len(fetched_docs) == 5
        fetched_ids = {d.metadata.id for d in fetched_docs}
        assert fetched_ids == set(doc_ids)


@pytest.mark.asyncio
async def test_slicer_parallel_batch_fetch_with_partial_failure(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify exceptions in candidate file reading are safely logged and discarded (PERF-01)."""
    import tars.slicer.engine as slicer_engine_module

    user_id = "test_user_partial_fail"
    good_doc_1 = "valid_doc_alpha"
    good_doc_2 = "valid_doc_beta"
    missing_doc = "missing_corrupted_doc"

    # Save only the good documents in storage
    for okf_id in [good_doc_1, good_doc_2]:
        doc = make_okf_doc(doc_id=okf_id, title=f"Title for {okf_id}")
        await storage_manager.save_okf_file(user_id=user_id, doc=doc)

    # Register all 3 in the database index (missing_doc will fail disk read)
    for okf_id in [good_doc_1, missing_doc, good_doc_2]:
        record = UserWikiIndex(
            user_id=user_id,
            okf_id=okf_id,
            title=f"Title for {okf_id}",
            type="concept",
            category="testing",
            importance="medium",
            tags=["unit_test"],
            file_path=f"storage/users/{user_id}/wikis/{okf_id}.md",
        )
        db_session.add(record)

    await db_session.commit()

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    with patch.object(slicer_engine_module.logger, "warning") as mock_warn:
        fetched_docs = await slicer._fetch_via_db(
            user_id=user_id,
            db_session=db_session,
            candidate_limit=10,
        )

    # Should safely return the 2 valid documents
    assert len(fetched_docs) == 2
    fetched_ids = [d.metadata.id for d in fetched_docs]
    assert good_doc_1 in fetched_ids
    assert good_doc_2 in fetched_ids
    assert missing_doc not in fetched_ids

    # Should log a warning for the missing file
    assert mock_warn.called
    assert any(missing_doc in str(call) for call in mock_warn.call_args_list)


@pytest.mark.asyncio
async def test_slicer_fetch_via_db_empty_records(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify _fetch_via_db returns empty list when user has no wiki records."""
    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    result = await slicer._fetch_via_db(
        user_id="nonexistent_user",
        db_session=db_session,
    )
    assert result == []


@pytest.mark.asyncio
async def test_slicer_end_to_end_slice_knowledge(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify end-to-end slice_knowledge pipeline functions with parallel batch pre-filtering."""
    user_id = "test_user_e2e"
    doc_pref = make_okf_doc(
        doc_id="user_coffee_pref",
        title="Coffee Preference",
        body="User prefers strong black espresso in the morning.",
        doc_type=OKFType.PREFERENCE,
        importance=OKFImportance.HIGH,
        tags=["coffee", "routine"],
    )
    await storage_manager.save_okf_file(user_id=user_id, doc=doc_pref)

    rec = UserWikiIndex(
        user_id=user_id,
        okf_id="user_coffee_pref",
        title="Coffee Preference",
        type="preference",
        category="routine",
        importance="high",
        tags=["coffee", "routine"],
        file_path=f"storage/users/{user_id}/wikis/user_coffee_pref.md",
    )
    db_session.add(rec)
    await db_session.commit()

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    result = await slicer.slice_knowledge(
        user_id=user_id,
        query="What coffee should I make?",
        token_budget=1000,
        profile="chat",
    )

    assert len(result.selected_documents) == 1
    assert result.selected_documents[0].id == "user_coffee_pref"
    assert "user_coffee_pref" in result.formatted_context
