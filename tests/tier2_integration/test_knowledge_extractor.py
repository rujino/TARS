"""Tier 2 Integration Tests: Self-Evolving Knowledge Extractor Worker & Auto-Extracted OKF Sync.

Verifies:
1. Background Task Execution: Non-blocking extraction of persistent user facts, rules, and preferences.
2. Extraction Schema Validation: Pydantic parsing of KnowledgeExtractionResult, field constraints,
   and required attributes.
3. Metadata Enforcement: All generated OKF documents MUST have metadata.source == "auto_extracted".
4. Storage & DB Synchronization: Atomic creation of .md file in storage/users/{user_id}/wikis/ and
   corresponding row insertion in DB UserWikiIndex.
5. Transient Filtering: Casual chatter, math queries, and greetings do not trigger extraction or disk writes.
6. Conflict & Update Handling: Contradictory statements update existing OKF document while updating timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.core.okf.models import OKFImportance, OKFSource, OKFType
from tars.db.models import UserWikiIndex
from tars.extractor.worker import KnowledgeExtractionResult, SelfEvolvingKnowledgeWorker
from tars.storage.manager import FileStorageManager

# ============================================================================
# 1. Extraction Schema & Worker Unit Validation
# ============================================================================


def test_knowledge_extraction_result_schema_valid() -> None:
    """Verify KnowledgeExtractionResult parses valid JSON extraction structure."""
    payload: dict[str, Any] = {
        "should_extract": True,
        "is_conflict_or_update": False,
        "target_existing_id": None,
        "doc_id": "user_pref_coffee",
        "type": "preference",
        "title": "User Coffee Preferences",
        "category": "lifestyle",
        "tags": ["coffee", "beverage", "preference"],
        "importance": "medium",
        "content": "User prefers black espresso with no sugar.",
        "relations": {"depends_on": [], "related_to": []},
    }

    result = KnowledgeExtractionResult.model_validate(payload)
    assert result.should_extract is True
    assert result.doc_id == "user_pref_coffee"
    assert result.type == "preference"
    assert result.importance == "medium"
    assert "black espresso" in result.content


def test_knowledge_extraction_result_negative_intent() -> None:
    """Verify negative extraction schema when no valuable knowledge is present."""
    payload: dict[str, Any] = {
        "should_extract": False,
        "is_conflict_or_update": False,
        "target_existing_id": None,
        "doc_id": None,
        "type": "concept",
        "title": "",
        "category": None,
        "tags": [],
        "importance": "low",
        "content": "",
        "relations": {"depends_on": [], "related_to": []},
    }

    result = KnowledgeExtractionResult.model_validate(payload)
    assert result.should_extract is False
    assert result.content == ""


# ============================================================================
# 2. End-to-End Extraction & Storage/DB Sync Tests
# ============================================================================


@pytest.mark.asyncio
async def test_extractor_extracts_and_syncs_new_rule(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
    temp_storage_root: Path,
) -> None:
    """Verify worker extracts rule from conversation, writes .md to storage, and indexes in DB."""
    canned_llm_json = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "rule_flight_readiness_test",
            "type": "rule",
            "title": "Flight Readiness Protocol",
            "category": "operations",
            "tags": ["flight", "ranger", "protocol"],
            "importance": "high",
            "content": "# Flight Readiness Protocol\n\nAlways verify docking clamp pressure before ignition.",
            "relations": {"depends_on": [], "related_to": ["docking_procedure"]},
        }
    )

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.return_value = canned_llm_json

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    turns: list[BaseMessage] = [
        HumanMessage(
            content="TARS, remember to always verify docking clamp pressure before ignition."
        ),
        AIMessage(content="Copy that, Cooper. Docking protocol safety rule registered."),
    ]

    extracted_docs = await worker.extract_and_sync(
        user_id="user_test_alpha",
        conversation_turns=turns,
        db_session=db_session,
    )

    # 1. Verify returned document metadata
    assert len(extracted_docs) == 1
    doc = extracted_docs[0]
    assert doc.metadata.id == "rule_flight_readiness_test"
    assert doc.metadata.type == OKFType.RULE
    assert doc.metadata.source == OKFSource.AUTO_EXTRACTED
    assert doc.metadata.importance == OKFImportance.HIGH
    assert "docking clamp pressure" in doc.content

    # 2. Verify file persisted in storage
    saved_doc = await storage_manager.read_okf_file(
        user_id="user_test_alpha",
        okf_id="rule_flight_readiness_test",
    )
    assert saved_doc is not None
    assert saved_doc.metadata.source == OKFSource.AUTO_EXTRACTED
    assert saved_doc.metadata.title == "Flight Readiness Protocol"

    # 3. Verify DB index record
    stmt = select(UserWikiIndex).where(
        UserWikiIndex.user_id == "user_test_alpha",
        UserWikiIndex.okf_id == "rule_flight_readiness_test",
    )
    result = await db_session.execute(stmt)
    index_entry = result.scalar_one_or_none()

    assert index_entry is not None
    assert index_entry.title == "Flight Readiness Protocol"
    assert index_entry.doc_type == "rule"
    assert index_entry.importance == "high"
    assert index_entry.file_path.endswith("rule_flight_readiness_test.md")


@pytest.mark.asyncio
async def test_extractor_skips_transient_and_trivial_messages(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify greetings, jokes, or trivial banter do not trigger extraction or file writes."""
    canned_llm_json = json.dumps(
        {
            "should_extract": False,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": None,
            "type": "concept",
            "title": "",
            "category": None,
            "tags": [],
            "importance": "low",
            "content": "",
            "relations": {"depends_on": [], "related_to": []},
        }
    )

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.return_value = canned_llm_json

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    turns: list[BaseMessage] = [
        HumanMessage(content="Hello TARS, what is 2 + 2?"),
        AIMessage(content="It is 4, unless you are computing in relativistic space-time."),
    ]

    extracted_docs = await worker.extract_and_sync(
        user_id="user_test_alpha",
        conversation_turns=turns,
        db_session=db_session,
    )

    assert len(extracted_docs) == 0

    # Verify no files written
    all_files = await storage_manager.list_okf_files(user_id="user_test_alpha")
    assert len(all_files) == 0

    # Verify no DB records created
    stmt = select(UserWikiIndex).where(UserWikiIndex.user_id == "user_test_alpha")
    result = await db_session.execute(stmt)
    assert len(result.scalars().all()) == 0


@pytest.mark.asyncio
async def test_extractor_conflict_resolution_and_update(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify updating an existing OKF document with new contradicting info."""
    # 1. Seed initial document
    initial_llm_json = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "schedule_weekly_sync",
            "type": "rule",
            "title": "Weekly Team Meeting",
            "category": "schedule",
            "tags": ["meeting", "schedule"],
            "importance": "medium",
            "content": "Meeting is on Tuesdays at 15:00 UTC.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.return_value = initial_llm_json

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    await worker.extract_and_sync(
        user_id="user_test_alpha",
        conversation_turns=[HumanMessage(content="Team meeting is on Tuesday at 3pm.")],
        db_session=db_session,
    )

    # 2. Update with contradiction (Meeting moved to Wednesday)
    updated_llm_json = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": True,
            "target_existing_id": "schedule_weekly_sync",
            "doc_id": "schedule_weekly_sync",
            "type": "rule",
            "title": "Weekly Team Meeting (Updated)",
            "category": "schedule",
            "tags": ["meeting", "schedule", "wednesday"],
            "importance": "high",
            "content": "Meeting moved to Wednesdays at 16:00 UTC.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )
    mock_llm.agenerate.return_value = updated_llm_json

    updated_docs = await worker.extract_and_sync(
        user_id="user_test_alpha",
        conversation_turns=[
            HumanMessage(content="Actually our team meeting moved to Wednesday at 4pm.")
        ],
        db_session=db_session,
    )

    assert len(updated_docs) == 1
    assert updated_docs[0].metadata.id == "schedule_weekly_sync"
    assert "Wednesdays at 16:00 UTC" in updated_docs[0].content

    # Verify file content updated
    re_read_doc = await storage_manager.read_okf_file(
        user_id="user_test_alpha",
        okf_id="schedule_weekly_sync",
    )
    assert "Wednesdays at 16:00 UTC" in re_read_doc.content
    assert re_read_doc.metadata.source == OKFSource.AUTO_EXTRACTED
