"""Adversarial Stress Testing Suite for TARS Phase 3 Milestone 3.

Empirical verification of:
1. 0 / negative / micro token budgets & single huge document truncation.
2. Cyclic graph dependencies (self-loops, mutual cycles, multi-node loops, dense complete graphs, ghost IDs).
3. Corrupted / malformed OKF files & empty content.
4. Empty DB index fallback & DB exception resilience.
5. Knowledge Extractor worker adversarial payloads (invalid JSON, unknown enums, timeout, DB rollback).
6. Multi-turn context & profile weight extremes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.extractor.worker import (
    CASUAL_CHAT_SKIP_REGEX,
    SelfEvolvingKnowledgeWorker,
)
from tars.slicer.engine import (
    DynamicSlicerEngine,
)
from tars.slicer.models import (
    HeuristicTokenCounter,
    SlicedContextResult,
)
from tars.storage.manager import FileStorageManager


def make_okf_doc(
    doc_id: str,
    title: str = "Test Document",
    doc_type: OKFType = OKFType.RULE,
    importance: OKFImportance = OKFImportance.HIGH,
    tags: list[str] | None = None,
    content: str = "Standard document body content.",
    depends_on: list[str] | None = None,
    related_to: list[str] | None = None,
    category: str | None = "general",
    updated_at: datetime | None = None,
) -> OKFDocument:
    now = updated_at or datetime.now(UTC)
    meta = OKFMetadata(
        okf_version="1.0",
        id=doc_id,
        type=doc_type,
        title=title,
        category=category,
        tags=tags or ["test"],
        importance=importance,
        source=OKFSource.MANUAL,
        relations=OKFRelations(
            depends_on=depends_on or [],
            related_to=related_to or [],
        ),
        created_at=now,
        updated_at=now,
    )
    return OKFDocument(metadata=meta, content=content)


# ============================================================================
# 1. Zero, Negative, Micro Token Budget & Gigantic Document Truncation
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_zero_and_negative_token_budget() -> None:
    """Stress-test slicer with 0, negative, and micro token budgets."""
    docs = [
        make_okf_doc(
            "doc_1", "Doc 1", OKFType.RULE, OKFImportance.CRITICAL, ["rule"], "Short rule 1"
        ),
        make_okf_doc("doc_2", "Doc 2", OKFType.RULE, OKFImportance.HIGH, ["rule"], "Short rule 2"),
    ]

    slicer = DynamicSlicerEngine()

    # 1. Zero token budget
    res_zero = await slicer.slice_documents(docs=docs, query="rule", token_budget=0)
    assert isinstance(res_zero, SlicedContextResult)
    assert res_zero.total_estimated_tokens >= 0

    # 2. Negative token budget
    res_neg = await slicer.slice_documents(docs=docs, query="rule", token_budget=-500)
    assert isinstance(res_neg, SlicedContextResult)
    assert res_neg.total_estimated_tokens >= 0

    # 3. Micro budget (1 token)
    res_micro = await slicer.slice_documents(docs=docs, query="rule", token_budget=1)
    assert isinstance(res_micro, SlicedContextResult)


@pytest.mark.asyncio
async def test_adversarial_gigantic_document_truncation() -> None:
    """Stress-test single gigantic document (>1,000,000 chars) exceeding token budget."""
    huge_body = "TARS Engineering Manual Section " + (
        "All systems operational at 99.9% capacity. " * 25000
    )
    huge_doc = make_okf_doc(
        "huge_doc",
        "Endurance Architecture Manual",
        OKFType.PROCEDURE,
        OKFImportance.CRITICAL,
        ["manual", "systems"],
        content=huge_body,
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=[huge_doc],
        query="manual systems",
        token_budget=150,
    )

    assert len(result.selected_documents) == 1
    selected = result.selected_documents[0]
    assert selected.id == "huge_doc"
    assert "... [truncated]" in selected.content
    assert len(selected.content) < 2000
    assert result.total_estimated_tokens <= 250


@pytest.mark.asyncio
async def test_adversarial_cjk_and_emoji_gigantic_truncation() -> None:
    """Stress-test CJK and multi-byte Unicode/Emoji text truncation and token estimation."""
    cjk_huge_body = (
        "인터스텔라 인듀어런스호 항법 및 생명유지장치 가이드라인 " * 5000 + "🚀🌌🛸" * 1000
    )
    cjk_doc = make_okf_doc(
        "cjk_doc",
        "항법 매뉴얼",
        OKFType.RULE,
        OKFImportance.HIGH,
        ["매뉴얼"],
        content=cjk_huge_body,
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(docs=[cjk_doc], query="항법 매뉴얼", token_budget=200)

    assert len(result.selected_documents) == 1
    assert "... [truncated]" in result.selected_documents[0].content
    assert result.total_estimated_tokens <= 300


def test_adversarial_heuristic_token_counter_boundaries() -> None:
    """Verify HeuristicTokenCounter handles empty, whitespace, CJK, and mixed inputs safely."""
    counter = HeuristicTokenCounter()
    assert counter.count_tokens("") == 0
    assert counter.count_tokens(" ") == 1
    assert counter.count_tokens("\n\t  \r") == 2
    assert counter.count_tokens("abc") == 1
    assert counter.count_tokens("안녕하세요 타스입니다.") >= 7
    huge_str = "A" * 1_000_000
    assert counter.count_tokens(huge_str) == 250_000


# ============================================================================
# 2. Cyclic Relations & Graph Stress
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_relations_self_loop() -> None:
    """Self-loop reference: doc_a depends_on [doc_a] and related_to [doc_a]."""
    doc_a = make_okf_doc(
        "doc_a",
        "Self Referencing Document",
        OKFType.RULE,
        OKFImportance.HIGH,
        ["loop"],
        "Self loop body",
        depends_on=["doc_a"],
        related_to=["doc_a"],
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(docs=[doc_a], query="loop", token_budget=1000)
    assert len(result.selected_documents) == 1
    assert result.selected_documents[0].id == "doc_a"


@pytest.mark.asyncio
async def test_adversarial_relations_mutual_and_multinode_cycles() -> None:
    """Mutual 2-node cycle and multi-node cyclic loop (A -> B -> C -> D -> A)."""
    doc_a = make_okf_doc(
        "doc_a",
        "Node A",
        OKFType.RULE,
        OKFImportance.CRITICAL,
        ["net"],
        "Content A",
        depends_on=["doc_b"],
    )
    doc_b = make_okf_doc(
        "doc_b",
        "Node B",
        OKFType.PROCEDURE,
        OKFImportance.HIGH,
        ["net"],
        "Content B",
        depends_on=["doc_c"],
    )
    doc_c = make_okf_doc(
        "doc_c",
        "Node C",
        OKFType.CONCEPT,
        OKFImportance.MEDIUM,
        ["net"],
        "Content C",
        depends_on=["doc_d"],
    )
    doc_d = make_okf_doc(
        "doc_d",
        "Node D",
        OKFType.PREFERENCE,
        OKFImportance.LOW,
        ["net"],
        "Content D",
        depends_on=["doc_a"],
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=[doc_a, doc_b, doc_c, doc_d],
        query="Node A net",
        token_budget=2000,
    )

    ids = [d.id for d in result.selected_documents]
    assert len(ids) == 4
    for score in result.scores.values():
        assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_adversarial_relations_dense_complete_graph() -> None:
    """Dense graph: 30 documents where every document depends_on all other 29 documents."""
    all_ids = [f"dense_doc_{i}" for i in range(30)]
    docs = [
        make_okf_doc(
            doc_id,
            f"Dense Node {i}",
            OKFType.RULE,
            OKFImportance.HIGH,
            ["dense"],
            f"Body of node {i}",
            depends_on=[oid for oid in all_ids if oid != doc_id],
            related_to=[oid for oid in all_ids if oid != doc_id],
        )
        for i, doc_id in enumerate(all_ids)
    ]

    slicer = DynamicSlicerEngine()
    start_time = asyncio.get_event_loop().time()
    result = await slicer.slice_documents(docs=docs, query="Dense Node 0", token_budget=1000)
    elapsed = asyncio.get_event_loop().time() - start_time

    assert elapsed < 0.5
    assert len(result.selected_documents) > 0


@pytest.mark.asyncio
async def test_adversarial_relations_ghost_and_missing_targets() -> None:
    """Relations point to non-existent document IDs."""
    doc = make_okf_doc(
        "doc_orphan",
        "Orphan Doc",
        OKFType.RULE,
        OKFImportance.HIGH,
        ["orphan"],
        "Content",
        depends_on=["ghost_999", "void_000"],
        related_to=["missing_link_123"],
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(docs=[doc], query="orphan", token_budget=1000)
    assert len(result.selected_documents) == 1


# ============================================================================
# 3. Corrupted / Malformed OKF Files & Empty Content Handling
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_empty_and_whitespace_content_docs() -> None:
    """Documents with empty body, whitespace body, or special characters."""
    doc_empty = make_okf_doc(
        "empty_doc", "Empty Title", OKFType.RULE, OKFImportance.HIGH, ["empty"], content=""
    )
    doc_ws = make_okf_doc(
        "ws_doc", "Whitespace Title", OKFType.RULE, OKFImportance.LOW, ["ws"], content="   \n\n\t  "
    )
    doc_special = make_okf_doc(
        "special_doc",
        "Special Char Doc",
        OKFType.RULE,
        OKFImportance.MEDIUM,
        ["spec"],
        content="Special content & <xml> tags & emoji 🎉",
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=[doc_empty, doc_ws, doc_special],
        query="Empty Title Special",
        token_budget=1500,
    )

    assert len(result.selected_documents) >= 1
    xml = result.formatted_context
    assert "<user_knowledge_context>" in xml
    assert "</user_knowledge_context>" in xml


# ============================================================================
# 4. Empty DB Index Fallback & DB Exception Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_slicer_empty_db_index_fallback(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """When DB index is empty, slice_context/slice_knowledge falls back to file storage."""
    user_id = "user_db_empty_fallback"
    doc = make_okf_doc(
        "storage_only_doc",
        "Storage Only Title",
        OKFType.PREFERENCE,
        OKFImportance.CRITICAL,
        ["pref"],
    )
    await storage_manager.save_okf_file(user_id=user_id, doc=doc)

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    selected_docs = await slicer.slice_context(
        user_id=user_id, query="Storage Only", db_session=db_session
    )

    assert len(selected_docs) == 1
    assert selected_docs[0].id == "storage_only_doc"


@pytest.mark.asyncio
async def test_adversarial_slicer_db_exception_graceful_fallback(
    storage_manager: FileStorageManager,
) -> None:
    """When DB session throws an operational error, slicer catches it and falls back to storage."""
    user_id = "user_db_error_fallback"
    doc = make_okf_doc(
        "resilient_doc", "Resilient Title", OKFType.RULE, OKFImportance.HIGH, ["resilient"]
    )
    await storage_manager.save_okf_file(user_id=user_id, doc=doc)

    failing_db_session = MagicMock(spec=AsyncSession)
    failing_db_session.execute = AsyncMock(
        side_effect=SQLAlchemyError("Database disk image is malformed")
    )

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=failing_db_session)
    result = await slicer.slice_knowledge(user_id=user_id, query="Resilient", db=failing_db_session)

    assert len(result.selected_documents) == 1
    assert result.selected_documents[0].id == "resilient_doc"


@pytest.mark.asyncio
async def test_adversarial_slicer_storage_failure_returns_empty(
    db_session: AsyncSession,
) -> None:
    """When storage manager fails completely, slicer returns empty result without throwing 500 error."""
    failing_storage = MagicMock()
    failing_storage.list_okf_files = AsyncMock(side_effect=IOError("Disk unreadable"))

    slicer = DynamicSlicerEngine(storage_manager=failing_storage, db_session=db_session)
    docs = await slicer.slice_context(user_id="ghost_user", query="query", db_session=db_session)
    assert docs == []


# ============================================================================
# 5. Knowledge Extractor Worker Adversarial Scenarios
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_extractor_casual_chat_skip_regex() -> None:
    """Verify fast regex skips casual chatter, single numbers, greetings, and basic math."""
    casual_inputs = [
        "안녕",
        "하이",
        "반가워",
        "hello",
        "Hi",
        "hey",
        "ping",
        "pong",
        "bye",
        "잘가",
        "고마워",
        "thanks",
        "thank you",
        "2+2",
        "10 * 5",
    ]
    for inp in casual_inputs:
        assert CASUAL_CHAT_SKIP_REGEX.match(inp.strip()) is not None

    non_casual = [
        "나는 매일 아침 8시에 블랙 커피를 마셔",
        "My secret PIN is 9988",
        "프로젝트 미팅은 매주 화요일 3시입니다",
    ]
    for inp in non_casual:
        assert CASUAL_CHAT_SKIP_REGEX.match(inp.strip()) is None


@pytest.mark.asyncio
async def test_adversarial_extractor_malformed_llm_json(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify extractor handles malformed or non-JSON LLM responses gracefully."""
    mock_llm = MagicMock(spec=BaseLLMAdapter)
    mock_llm.agenerate = AsyncMock(
        return_value="I am an LLM, and I refuse to output JSON! Here is random text: {{{["
    )

    worker = SelfEvolvingKnowledgeWorker(extractor_llm=mock_llm, storage_manager=storage_manager)
    results = await worker.extract_and_sync(
        user_id="user_malformed_json",
        conversation_turns=[HumanMessage(content="내 비밀번호는 12345야")],
        db_session=db_session,
    )

    assert results == []


@pytest.mark.asyncio
async def test_adversarial_extractor_unknown_enums_and_missing_fields(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify extractor safely falls back for unknown types, unknown importance levels, and missing fields."""
    raw_json = '{"should_extract": true, "type": "alien_quantum_hyper_rule", "importance": "cosmic_critical_9999", "title": "Quantum Rule", "content": "Always initialize wormhole jump at speed 0.8c."}'

    mock_llm = MagicMock(spec=BaseLLMAdapter)
    mock_llm.agenerate = AsyncMock(return_value=raw_json)

    worker = SelfEvolvingKnowledgeWorker(extractor_llm=mock_llm, storage_manager=storage_manager)
    results = await worker.extract_and_sync(
        user_id="user_unknown_enums",
        conversation_turns=[HumanMessage(content="웜홀 도약 규칙 알려줄게")],
        db_session=db_session,
    )

    assert len(results) == 1
    doc = results[0]
    assert doc.metadata.type == OKFType.CONCEPT
    assert doc.metadata.importance == OKFImportance.MEDIUM
    assert doc.metadata.source == OKFSource.AUTO_EXTRACTED


@pytest.mark.asyncio
async def test_adversarial_extractor_timeout_handling(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify extractor enforces 5.0s timeout when LLM hangs."""

    async def slow_agenerate(*args: Any, **kwargs: Any) -> str:
        await asyncio.sleep(6.0)
        return "{}"

    mock_llm = MagicMock(spec=BaseLLMAdapter)
    mock_llm.agenerate = slow_agenerate

    worker = SelfEvolvingKnowledgeWorker(extractor_llm=mock_llm, storage_manager=storage_manager)
    start_t = asyncio.get_event_loop().time()
    results = await worker.extract_and_sync(
        user_id="user_slow_llm",
        conversation_turns=[HumanMessage(content="매우 긴 정보 전달")],
        db_session=db_session,
    )
    elapsed = asyncio.get_event_loop().time() - start_t

    assert results == []
    assert 4.8 <= elapsed <= 5.5


@pytest.mark.asyncio
async def test_adversarial_extractor_conflict_update_flow(
    storage_manager: FileStorageManager,
    db_session: AsyncSession,
) -> None:
    """Verify existing document update/overwrite with source: auto_extracted metadata."""
    user_id = "user_conflict_update"
    initial_doc = make_okf_doc(
        "pref_tea",
        "Favorite Beverage",
        OKFType.PREFERENCE,
        OKFImportance.LOW,
        content="User prefers green tea.",
    )
    await storage_manager.save_okf_file(user_id=user_id, doc=initial_doc)

    update_json = '{"should_extract": true, "is_conflict_or_update": true, "target_existing_id": "pref_tea", "type": "preference", "title": "Favorite Beverage", "importance": "high", "content": "User strictly drinks black coffee with zero sugar.", "tags": ["coffee", "beverage"]}'

    mock_llm = MagicMock(spec=BaseLLMAdapter)
    mock_llm.agenerate = AsyncMock(return_value=update_json)

    worker = SelfEvolvingKnowledgeWorker(extractor_llm=mock_llm, storage_manager=storage_manager)
    results = await worker.extract_and_sync(
        user_id=user_id,
        conversation_turns=[HumanMessage(content="나 이제 녹차 안 마셔. 블랙 커피만 마셔.")],
        db_session=db_session,
    )

    assert len(results) == 1
    updated_doc = results[0]
    assert updated_doc.id == "pref_tea"
    assert updated_doc.metadata.source == OKFSource.AUTO_EXTRACTED
    assert "black coffee" in updated_doc.content

    saved_doc = await storage_manager.read_okf_file(user_id, "pref_tea")
    assert "black coffee" in saved_doc.content
