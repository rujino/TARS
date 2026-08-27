"""Tier 2 Adversarial Integration Tests: Empirical Verification of Knowledge Self-Evolving Loop.

Adversarial Stress-Testing Scenarios:
1. Concurrent Race Conditions: High-throughput concurrent extraction bursts & race on identical document IDs.
2. Contradictory Updates & Atomic Evolution: Multi-stage rapid contradiction lifecycle with file/DB reconciliation.
3. Casual Chat Filtering & Boundary Accuracy: Regex edge cases, false positive prevention, and malformed LLM responses.
4. Fault Isolation & Main Chat Non-blocking: LLM timeouts, adapter crashes, DB rollback resilience.
5. Full Closed-Loop Evolution: Auto-extracted knowledge injection into Dynamic Slicer and Proactive Greeting.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tars.adapters.base import BaseLLMAdapter
from tars.api.routers.chat import _execute_background_knowledge_extraction
from tars.core.okf.models import OKFImportance, OKFSource
from tars.db.models import UserWikiIndex
from tars.extractor.worker import (
    CASUAL_CHAT_SKIP_REGEX,
    SelfEvolvingKnowledgeWorker,
)
from tars.services.greeting import ProactiveGreetingService
from tars.slicer.engine import DynamicSlicerEngine
from tars.slicer.models import SlicerProfile
from tars.storage.manager import FileStorageManager

# ============================================================================
# 1. Concurrent Extraction Race Condition & Burst Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_extraction_race_condition_burst(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Stress-test: 10 concurrent background extraction tasks for the same user."""
    storage_manager = FileStorageManager(base_dir=temp_storage_root)
    user_id = "user_stress_concurrent"

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    num_concurrent = 10

    async def run_single_extraction(idx: int) -> None:
        canned_json = json.dumps(
            {
                "should_extract": True,
                "is_conflict_or_update": False,
                "target_existing_id": None,
                "doc_id": f"pref_burst_item_{idx:02d}",
                "type": "preference",
                "title": f"Preference Item {idx}",
                "category": "lifestyle",
                "tags": ["burst", f"tag_{idx}"],
                "importance": "medium",
                "content": f"User preference rule number {idx}.",
                "relations": {"depends_on": [], "related_to": []},
            }
        )
        mock_llm = AsyncMock(spec=BaseLLMAdapter)
        mock_llm.agenerate.return_value = canned_json

        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=mock_llm,
            storage_manager=storage_manager,
        )

        async with session_factory() as session:
            turns = [HumanMessage(content=f"Remember my preference #{idx}")]
            docs = await worker.extract_and_sync(
                user_id=user_id,
                conversation_turns=turns,
                db_session=session,
            )
            assert len(docs) == 1
            assert docs[0].metadata.id == f"pref_burst_item_{idx:02d}"

    # Execute all 10 extractions concurrently
    await asyncio.gather(*(run_single_extraction(i) for i in range(num_concurrent)))

    # Verify all 10 files exist on disk
    saved_files = await storage_manager.list_okf_files(user_id=user_id)
    assert len(saved_files) == num_concurrent

    # Ensure full storage-DB reconciliation sync
    async with session_factory() as session:
        from tars.storage.reconciliation import StorageDBReconciliationEngine

        recon_engine = StorageDBReconciliationEngine(storage_manager=storage_manager)
        recon_result = await recon_engine.reconcile_user(session=session, user_id=user_id)
        await session.commit()

        stmt = (
            select(func.count()).select_from(UserWikiIndex).where(UserWikiIndex.user_id == user_id)
        )
        res = await session.execute(stmt)
        count = res.scalar_one()
        assert count == num_concurrent
        assert recon_result.is_clean


@pytest.mark.asyncio
async def test_concurrent_extraction_on_same_document_id(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Stress-test: Multiple concurrent tasks competing to update the exact same document ID."""
    storage_manager = FileStorageManager(base_dir=temp_storage_root)
    user_id = "user_same_doc_race"
    target_id = "pref_shared_schedule"

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def run_competing_update(idx: int) -> None:
        canned_json = json.dumps(
            {
                "should_extract": True,
                "is_conflict_or_update": True,
                "target_existing_id": target_id,
                "doc_id": target_id,
                "type": "rule",
                "title": f"Weekly Schedule Version {idx}",
                "category": "schedule",
                "tags": ["schedule", f"v{idx}"],
                "importance": "high",
                "content": f"Team meeting is at version {idx}:00 UTC.",
                "relations": {"depends_on": [], "related_to": []},
            }
        )
        mock_llm = AsyncMock(spec=BaseLLMAdapter)
        mock_llm.agenerate.return_value = canned_json

        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=mock_llm,
            storage_manager=storage_manager,
        )

        async with session_factory() as session:
            await worker.extract_and_sync(
                user_id=user_id,
                conversation_turns=[HumanMessage(content=f"Change meeting time to v{idx}")],
                db_session=session,
            )

    # 5 concurrent tasks trying to overwrite the same doc_id
    await asyncio.gather(*(run_competing_update(i) for i in range(5)))

    # Exactly 1 file should exist for that ID on disk
    saved_doc = await storage_manager.read_okf_file(user_id=user_id, okf_id=target_id)
    assert saved_doc is not None
    assert saved_doc.metadata.id == target_id
    assert saved_doc.metadata.source == OKFSource.AUTO_EXTRACTED

    # Reconcile DB index to ensure absolute consistency
    async with session_factory() as session:
        from tars.storage.reconciliation import StorageDBReconciliationEngine

        recon_engine = StorageDBReconciliationEngine(storage_manager=storage_manager)
        await recon_engine.reconcile_user(session=session, user_id=user_id)
        await session.commit()

        stmt = select(UserWikiIndex).where(
            UserWikiIndex.user_id == user_id,
            UserWikiIndex.okf_id == target_id,
        )
        res = await session.execute(stmt)
        records = res.scalars().all()
        assert len(records) == 1


@pytest.mark.asyncio
async def test_multi_tenant_concurrent_extraction_isolation(
    test_engine: AsyncEngine,
    temp_storage_root: Path,
) -> None:
    """Verify multi-tenant isolation under concurrent knowledge extraction."""
    storage_manager = FileStorageManager(base_dir=temp_storage_root)
    users = ["user_alpha", "user_beta", "user_gamma"]

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async def run_user_extraction(uid: str) -> None:
        canned_json = json.dumps(
            {
                "should_extract": True,
                "is_conflict_or_update": False,
                "target_existing_id": None,
                "doc_id": "pref_secret_code",
                "type": "fact",
                "title": f"Secret Code for {uid}",
                "category": "security",
                "tags": ["secret"],
                "importance": "critical",
                "content": f"Secret code for {uid} is 999-{uid}.",
                "relations": {"depends_on": [], "related_to": []},
            }
        )
        mock_llm = AsyncMock(spec=BaseLLMAdapter)
        mock_llm.agenerate.return_value = canned_json

        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=mock_llm,
            storage_manager=storage_manager,
        )

        async with session_factory() as session:
            await worker.extract_and_sync(
                user_id=uid,
                conversation_turns=[HumanMessage(content="Store my secret code")],
                db_session=session,
            )

    await asyncio.gather(*(run_user_extraction(u) for u in users))

    # Verify per-user storage isolation
    for u in users:
        files = await storage_manager.list_okf_files(user_id=u)
        assert len(files) == 1
        assert files[0].metadata.title == f"Secret Code for {u}"
        assert f"999-{u}" in files[0].content

    # Verify DB index isolation after reconciliation
    async with session_factory() as session:
        from tars.storage.reconciliation import StorageDBReconciliationEngine

        recon_engine = StorageDBReconciliationEngine(storage_manager=storage_manager)
        for u in users:
            await recon_engine.reconcile_user(session=session, user_id=u)
        await session.commit()

        for u in users:
            stmt = select(UserWikiIndex).where(UserWikiIndex.user_id == u)
            res = await session.execute(stmt)
            recs = res.scalars().all()
            assert len(recs) == 1
            assert recs[0].okf_id == "pref_secret_code"
            assert recs[0].user_id == u


# ============================================================================
# 2. Contradictory Updates & Atomic Evolution Lifecycle
# ============================================================================


@pytest.mark.asyncio
async def test_rapid_contradiction_lifecycle_atomic_update(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Stress-test: 4 sequential contradictory updates to the same preference document."""
    user_id = "user_contradiction_test"
    doc_id = "pref_favorite_beverage"

    stages = [
        ("black coffee", "Black Coffee Preference", OKFImportance.MEDIUM),
        ("green tea", "Switched to Green Tea", OKFImportance.HIGH),
        ("sparkling water only", "Strict Sparkling Water Policy", OKFImportance.HIGH),
        (
            "double espresso with oat milk",
            "Final Espresso & Oat Milk Choice",
            OKFImportance.CRITICAL,
        ),
    ]

    for idx, (beverage_text, title, importance) in enumerate(stages):
        is_update = idx > 0
        canned_json = json.dumps(
            {
                "should_extract": True,
                "is_conflict_or_update": is_update,
                "target_existing_id": doc_id if is_update else None,
                "doc_id": doc_id,
                "type": "preference",
                "title": title,
                "category": "beverage",
                "tags": ["drink", "preference", f"stage_{idx}"],
                "importance": importance.value,
                "content": f"User favorite drink is now {beverage_text}.",
                "relations": {"depends_on": [], "related_to": []},
            }
        )

        mock_llm = AsyncMock(spec=BaseLLMAdapter)
        mock_llm.agenerate.return_value = canned_json

        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=mock_llm,
            storage_manager=storage_manager,
        )

        docs = await worker.extract_and_sync(
            user_id=user_id,
            conversation_turns=[HumanMessage(content=f"My beverage is {beverage_text}")],
            db_session=db_session,
        )

        assert len(docs) == 1
        assert docs[0].metadata.id == doc_id
        assert beverage_text in docs[0].content
        assert docs[0].metadata.source == OKFSource.AUTO_EXTRACTED
        assert docs[0].metadata.importance == importance

        # DB must have exactly 1 record for this user and doc_id at all stages
        stmt = select(UserWikiIndex).where(
            UserWikiIndex.user_id == user_id,
            UserWikiIndex.okf_id == doc_id,
        )
        res = await db_session.execute(stmt)
        db_rows = res.scalars().all()
        assert len(db_rows) == 1
        assert db_rows[0].title == title
        assert db_rows[0].importance == importance.value

        # File content must match current stage
        file_doc = await storage_manager.read_okf_file(user_id=user_id, okf_id=doc_id)
        assert file_doc is not None
        assert beverage_text in file_doc.content


# ============================================================================
# 3. Casual Chat Filtering & Boundary Accuracy
# ============================================================================


def test_casual_chat_regex_edge_cases() -> None:
    """Verify regex boundary behavior: true positives vs false positive protection."""
    # True Positives: trivial chit-chat and basic math expressions that MUST be skipped
    trivial_messages = [
        "안녕",
        "하이",
        "반가워",
        "hello",
        "hi",
        "hey",
        "test",
        "ping",
        "pong",
        "bye",
        "goodbye",
        "잘가",
        "고마워",
        "thanks",
        "thank you",
        "2 + 2",
        "2+2",
        "100 / 5",
        "3 * 7",
        "50 - 10",
    ]
    for msg in trivial_messages:
        assert CASUAL_CHAT_SKIP_REGEX.match(msg.strip()) is not None, f"Expected match for: '{msg}'"

    # False Positives: messages containing meaningful information that MUST NOT be skipped by regex
    informational_messages = [
        "안녕, 내 이름은 쿠퍼이고 파일럿이야",
        "하이! 내 이메일은 cooper@endurance.space 야",
        "고마워! 내일 회의 일정은 오전 10시로 잡아줘",
        "hello TARS, my preferred language is Korean",
        "thanks, please remember my timezone is UTC+9",
        "2+2 is 4, but in relativistic flight mode calculations differ",
        "test the docking clamp pressure before every launch",
    ]
    for msg in informational_messages:
        assert CASUAL_CHAT_SKIP_REGEX.match(msg.strip()) is None, f"Expected NO match for: '{msg}'"


@pytest.mark.asyncio
async def test_extractor_skips_casual_regex_without_calling_llm(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Empirical check: 1st-stage regex skip does NOT invoke the LLM adapter (0ms token waste)."""
    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    for casual_text in ["안녕", "hello", "2 + 2", "thanks", "ping"]:
        docs = await worker.extract_and_sync(
            user_id="user_casual_test",
            conversation_turns=[HumanMessage(content=casual_text)],
            db_session=db_session,
        )
        assert len(docs) == 0

    # LLM must not have been called even once
    assert mock_llm.agenerate.call_count == 0


@pytest.mark.asyncio
async def test_extractor_handles_markdown_fences_and_noisy_llm_output(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify robust parsing of JSON wrapped in markdown code fences or surrounded by noise."""
    noisy_llm_output = """Here is the extracted knowledge payload:
```json
{
  "should_extract": true,
  "is_conflict_or_update": false,
  "target_existing_id": null,
  "doc_id": "pref_noisy_json_test",
  "type": "fact",
  "title": "Noisy JSON Payload",
  "category": "testing",
  "tags": ["noise", "robustness"],
  "importance": "high",
  "content": "Verified markdown code fences stripped successfully.",
  "relations": {"depends_on": [], "related_to": []}
}
```
I hope this format is satisfactory!"""

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.return_value = noisy_llm_output

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    docs = await worker.extract_and_sync(
        user_id="user_noisy_test",
        conversation_turns=[HumanMessage(content="Store my fact despite LLM noise")],
        db_session=db_session,
    )

    assert len(docs) == 1
    assert docs[0].metadata.id == "pref_noisy_json_test"
    assert "code fences stripped" in docs[0].content


@pytest.mark.asyncio
async def test_extractor_handles_corrupted_llm_json_gracefully(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify that malformed / non-JSON LLM responses do not raise uncaught exceptions."""
    broken_outputs = [
        "I am an AI and cannot fulfill this extraction request.",
        "{invalid_json: 123",
        "```json\n{'invalid_single_quotes': True}\n```",
        "",
    ]

    for broken in broken_outputs:
        mock_llm = AsyncMock(spec=BaseLLMAdapter)
        mock_llm.agenerate.return_value = broken

        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=mock_llm,
            storage_manager=storage_manager,
        )

        docs = await worker.extract_and_sync(
            user_id="user_corrupted_test",
            conversation_turns=[HumanMessage(content="Process this turn")],
            db_session=db_session,
        )
        assert docs == []


# ============================================================================
# 4. Fault Isolation & Main Chat Non-blocking
# ============================================================================


@pytest.mark.asyncio
async def test_extractor_llm_timeout_isolation(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify that slow LLM responses (exceeding 5.0s timeout) abort gracefully without crashing."""

    async def slow_llm_call(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(10.0)  # Exceeds 5.0s timeout
        return "{}"

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.side_effect = slow_llm_call

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    # Use patch to shorten timeout for faster test execution
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        docs = await worker.extract_and_sync(
            user_id="user_timeout_test",
            conversation_turns=[HumanMessage(content="Important fact here")],
            db_session=db_session,
        )
        assert docs == []


@pytest.mark.asyncio
async def test_extractor_llm_exception_isolation(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify that LLM adapter crashes (e.g. 500 error / network failure) are caught safely."""
    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate = AsyncMock(
        side_effect=RuntimeError("500 Internal Server Error: Model overloaded")
    )

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    docs = await worker.extract_and_sync(
        user_id="user_llm_crash_test",
        conversation_turns=[HumanMessage(content="Important fact")],
        db_session=db_session,
    )
    assert docs == []


@pytest.mark.asyncio
async def test_execute_background_knowledge_extraction_absolute_fault_isolation(
    temp_storage_root: Path,
) -> None:
    """Verify that _execute_background_knowledge_extraction catches all errors and closes DB cleanly."""
    storage_manager = FileStorageManager(base_dir=temp_storage_root)

    # 1. Test with empty / invalid turns
    await _execute_background_knowledge_extraction(
        user_id="",
        conversation_turns=[],
        storage=storage_manager,
    )

    # 2. Test with mock LLM throwing unhandled BaseException
    exploding_llm = AsyncMock(spec=BaseLLMAdapter)
    exploding_llm.agenerate = AsyncMock(side_effect=Exception("Catastrophic LLM failure"))

    # Should not raise exception to the caller
    await _execute_background_knowledge_extraction(
        user_id="user_isolated_test",
        conversation_turns=[
            HumanMessage(content="Hello"),
            AIMessage(content="World"),
        ],
        storage=storage_manager,
        llm_adapter=exploding_llm,
    )


# ============================================================================
# 5. Full Closed-Loop Evolution: Dynamic Slicer & Proactive Greeting
# ============================================================================


@pytest.mark.asyncio
async def test_full_self_evolving_closed_loop_slicing_and_greeting(
    db_session: AsyncSession,
    storage_manager: FileStorageManager,
) -> None:
    """Verify the entire closed loop:
    Turn 1: Extract knowledge -> Storage & DB
    Turn 2: Dynamic Slicer retrieves newly extracted knowledge into system prompt
    Turn 3: Proactive Greeting retrieves knowledge using GREETING profile
    """
    user_id = "user_closed_loop_test"

    # 1. Turn 1: Extract vegan diet preference
    extraction_json = json.dumps(
        {
            "should_extract": True,
            "is_conflict_or_update": False,
            "target_existing_id": None,
            "doc_id": "pref_dietary_vegan",
            "type": "preference",
            "title": "Strict Vegan Diet Preference",
            "category": "lifestyle",
            "tags": ["diet", "vegan", "nutrition"],
            "importance": "high",
            "content": "User follows a 100% strict vegan diet and avoids all animal products.",
            "relations": {"depends_on": [], "related_to": []},
        }
    )

    mock_llm = AsyncMock(spec=BaseLLMAdapter)
    mock_llm.agenerate.return_value = extraction_json

    worker = SelfEvolvingKnowledgeWorker(
        extractor_llm=mock_llm,
        storage_manager=storage_manager,
    )

    docs = await worker.extract_and_sync(
        user_id=user_id,
        conversation_turns=[HumanMessage(content="I only eat a strict vegan diet.")],
        db_session=db_session,
    )
    assert len(docs) == 1

    # 2. Turn 2: Dynamic Slicer Query
    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    sliced_wikis = await slicer.slice_context(
        user_id=user_id,
        query="점심 메뉴로 뭐가 좋을까? 추천해줘.",
        context_messages=[HumanMessage(content="점심 메뉴 추천해줘")],
        profile=SlicerProfile.CHAT,
    )

    # Slicer must have retrieved the newly extracted vegan preference
    assert len(sliced_wikis) >= 1
    found_vegan = any(
        "vegan" in w.content.lower() or "strict vegan" in w.metadata.title.lower()
        for w in sliced_wikis
    )
    assert found_vegan is True, "DynamicSlicer failed to retrieve newly extracted knowledge"

    # 3. Turn 3: Proactive Greeting generation
    greeting_llm = AsyncMock(spec=BaseLLMAdapter)
    greeting_llm.agenerate = AsyncMock(
        return_value="좋은 아침입니다, 파트너. 오늘도 맛있는 비건 식단으로 에너지를 충전하십시오."
    )

    greeting_service = ProactiveGreetingService(
        db_session=db_session,
        storage_manager=storage_manager,
        llm_adapter=greeting_llm,
    )

    greeting_resp = await greeting_service.generate_greeting(
        user_id=user_id,
        client_timezone="Asia/Seoul",
    )

    assert greeting_resp.greeting != ""
    assert "비건" in greeting_resp.greeting

    # Verify greeting service called LLM with prompt containing the extracted knowledge
    called_messages = greeting_llm.agenerate.call_args.kwargs.get("messages", [])
    assert len(called_messages) > 0
    prompt_text = str(called_messages[0].content)
    assert "Strict Vegan Diet Preference" in prompt_text or "vegan" in prompt_text.lower()
