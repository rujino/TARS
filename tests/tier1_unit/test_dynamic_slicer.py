"""Tier 1 Unit Tests: OKF Dynamic Knowledge Slicer (F6).

Covers:
- 5-Factor multi-factor scoring: context similarity (S_sim), importance (S_imp), type (S_type), relations boost (S_rel), recency (S_rec)
- Profiles: chat, greeting, task profiles with profile-specific weights and type hierarchies
- Multi-turn context token extraction & relevance matching
- Fast DB metadata candidate pre-filtering
- Token budget management & trimming: packing high-scoring documents within token budget
- Prompt context rendering: XML/Markdown format conforming to <user_knowledge_context>
- Edge cases: empty knowledge base, zero match queries, circular dependencies in relations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.db.models import UserWikiIndex
from tars.slicer.engine import (
    DynamicSlicerEngine,
    calculate_recency_score,
    extract_context_tokens,
    format_knowledge_context_markdown,
    format_knowledge_context_xml,
)
from tars.slicer.models import (
    SlicerProfile,
)

# ============================================================================
# Helpers
# ============================================================================


def build_doc(
    doc_id: str,
    title: str,
    doc_type: OKFType,
    importance: OKFImportance,
    tags: list[str],
    body: str,
    depends_on: list[str] | None = None,
    related_to: list[str] | None = None,
    updated_at: datetime | None = None,
    category: str | None = None,
) -> OKFDocument:
    now = updated_at or datetime.now(UTC)
    fm = OKFFrontmatter(
        id=doc_id,
        type=doc_type,
        title=title,
        tags=tags,
        category=category,
        importance=importance,
        source=OKFSource.MANUAL,
        relations=OKFRelations(
            depends_on=depends_on or [],
            related_to=related_to or [],
        ),
        created_at=now,
        updated_at=now,
    )
    return OKFDocument(metadata=fm, content=body)


# ============================================================================
# Dynamic Slicer Unit Tests (F6)
# ============================================================================


@pytest.mark.asyncio
async def test_slicer_tag_and_keyword_relevance_matching() -> None:
    """Verify that documents matching query keywords or tags achieve higher relevance score."""
    docs = [
        build_doc(
            "doc_meeting",
            "Weekly Team Meeting Schedule",
            OKFType.RULE,
            OKFImportance.HIGH,
            ["meeting", "tuesday", "schedule"],
            "Meeting occurs every Tuesday at 15:00.",
        ),
        build_doc(
            "doc_food",
            "Favorite Coffee Brands",
            OKFType.PREFERENCE,
            OKFImportance.LOW,
            ["coffee", "beverage"],
            "Prefers dark roast coffee.",
        ),
    ]

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=docs,
        query="When is our team meeting?",
        active_tags=["meeting"],
        token_budget=1500,
    )

    assert len(result.selected_documents) > 0
    top_doc = result.selected_documents[0]
    assert top_doc.id == "doc_meeting"


@pytest.mark.asyncio
async def test_slicer_importance_weighting_hierarchy() -> None:
    """Verify that higher importance level (CRITICAL > HIGH > MEDIUM > LOW) ranks documents higher when other factors are equal."""
    docs = [
        build_doc(
            "low_rule",
            "Low Priority Rule",
            OKFType.RULE,
            OKFImportance.LOW,
            ["rule"],
            "Low priority rule body",
        ),
        build_doc(
            "critical_rule",
            "Critical Security Rule",
            OKFType.RULE,
            OKFImportance.CRITICAL,
            ["rule"],
            "Critical security rule body",
        ),
        build_doc(
            "medium_rule",
            "Medium Rule",
            OKFType.RULE,
            OKFImportance.MEDIUM,
            ["rule"],
            "Medium rule body",
        ),
    ]

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=docs,
        query="What rules should I follow?",
        active_tags=["rule"],
        token_budget=2000,
    )

    doc_ids = [d.id for d in result.selected_documents]
    assert doc_ids.index("critical_rule") < doc_ids.index("medium_rule") < doc_ids.index("low_rule")


@pytest.mark.asyncio
async def test_slicer_token_budget_trimming() -> None:
    """Verify that documents exceeding the token/character budget are truncated or excluded."""
    docs = [
        build_doc(
            f"doc_{i}",
            f"Document {i}",
            OKFType.CONCEPT,
            OKFImportance.HIGH if i == 0 else OKFImportance.MEDIUM,
            ["common_tag"],
            f"Very long body content for document {i} " * 100,  # ~400 tokens each
        )
        for i in range(5)
    ]

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=docs,
        query="common_tag search query",
        token_budget=500,
    )

    assert len(result.selected_documents) < len(docs)
    assert result.selected_documents[0].id == "doc_0"
    assert result.total_estimated_tokens <= 600


@pytest.mark.asyncio
async def test_slicer_relations_expansion_and_cycle_prevention() -> None:
    """Verify that related_to and depends_on links are traversed and cycles are handled safely."""
    doc_a = build_doc(
        "doc_a",
        "Primary Mission",
        OKFType.RULE,
        OKFImportance.HIGH,
        ["mission"],
        "Primary mission instructions.",
        depends_on=["doc_b"],
    )
    doc_b = build_doc(
        "doc_b",
        "Secondary Safety Protocol",
        OKFType.PROCEDURE,
        OKFImportance.MEDIUM,
        ["safety"],
        "Secondary protocol instructions.",
        related_to=["doc_a"],
    )

    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=[doc_a, doc_b],
        query="What is the mission?",
        token_budget=1500,
    )

    selected_ids = [d.id for d in result.selected_documents]
    assert "doc_a" in selected_ids
    assert "doc_b" in selected_ids


@pytest.mark.asyncio
async def test_slicer_prompt_context_rendering_format() -> None:
    """Verify rendered context matches <user_knowledge_context> format with OKF headers."""
    doc = build_doc(
        "pref_tars",
        "TARS Settings",
        OKFType.PREFERENCE,
        OKFImportance.HIGH,
        ["persona"],
        "Dry wit 90% and honesty 95%.",
    )

    slicer = DynamicSlicerEngine()
    rendered_text = slicer.render_context_xml([doc])

    assert "<user_knowledge_context>" in rendered_text
    assert "</user_knowledge_context>" in rendered_text
    assert "[OKF: pref_tars | Type: preference | Importance: high]" in rendered_text
    assert "# TARS Settings" in rendered_text
    assert "Dry wit 90% and honesty 95%." in rendered_text

    # Markdown formatter
    md_text = format_knowledge_context_markdown([doc])
    assert "## Relevant Knowledge Context" in md_text
    assert "### [PREFERENCE] TARS Settings (id: pref_tars)" in md_text


@pytest.mark.asyncio
async def test_slicer_empty_knowledge_base_handling() -> None:
    """Verify slicer handles empty document list gracefully without crashing."""
    slicer = DynamicSlicerEngine()
    result = await slicer.slice_documents(
        docs=[],
        query="Anything about meetings?",
        token_budget=1500,
    )

    assert result.selected_documents == []
    assert slicer.render_context_xml([]) == ""
    assert format_knowledge_context_markdown([]) == ""
    assert format_knowledge_context_xml([]) == "<user_knowledge_context>\n</user_knowledge_context>"


# ============================================================================
# 5-Factor Multi-Factor & Profile Advanced Unit Tests (M3)
# ============================================================================


def test_recency_score_exponential_decay() -> None:
    """Verify recency score decays exponentially as document age increases."""
    now = datetime.now(UTC)
    doc_fresh = now - timedelta(hours=1)
    doc_15d = now - timedelta(days=15)
    doc_30d = now - timedelta(days=30)
    doc_120d = now - timedelta(days=120)

    score_fresh = calculate_recency_score(doc_fresh)
    score_15d = calculate_recency_score(doc_15d)
    score_30d = calculate_recency_score(doc_30d)
    score_120d = calculate_recency_score(doc_120d)

    assert 0.95 <= score_fresh <= 1.0
    assert 0.55 <= score_15d <= 0.65
    assert 0.30 <= score_30d <= 0.40
    assert score_120d == 0.05  # Floor minimum


def test_context_tokens_extraction() -> None:
    """Verify extract_context_tokens parses strings, messages, and dicts correctly."""
    messages: list[str | BaseMessage | dict[str, Any]] = [
        HumanMessage(content="We are planning the Mars expedition schedule."),
        AIMessage(content="Understood. Life support verification is required."),
        {"role": "user", "content": "Check oxygen scrubbers."},
    ]

    tokens = extract_context_tokens(messages)
    assert "mars" in tokens
    assert "expedition" in tokens
    assert "oxygen" in tokens
    assert "scrubbers" in tokens


@pytest.mark.asyncio
async def test_slicer_multi_turn_context_relevance() -> None:
    """Verify multi-turn conversation context raises the relevance of related knowledge."""
    doc_mars = build_doc(
        "doc_mars_oxygen",
        "Mars Life Support Protocols",
        OKFType.PROCEDURE,
        OKFImportance.HIGH,
        ["mars", "oxygen", "life_support"],
        "Ensure carbon dioxide scrubbers are cleaned every 48 hours.",
    )
    doc_generic = build_doc(
        "doc_generic",
        "Generic Station Cleaning",
        OKFType.PROCEDURE,
        OKFImportance.LOW,
        ["cleaning"],
        "Mop floors daily.",
    )

    slicer = DynamicSlicerEngine()
    context = [
        HumanMessage(content="We are landing on Mars tomorrow."),
        AIMessage(content="Preparing touchdown checklist."),
    ]

    # Query without explicit "mars" keyword, but context contains "Mars"
    result = await slicer.slice_documents(
        docs=[doc_generic, doc_mars],
        query="What scrubbers need cleaning?",
        context_messages=context,
        token_budget=1500,
    )

    assert len(result.selected_documents) > 0
    assert result.selected_documents[0].id == "doc_mars_oxygen"


@pytest.mark.asyncio
async def test_slicer_profiles_chat_vs_greeting_differentiation() -> None:
    """Verify greeting profile favors user preferences and rules, while chat profile focuses on query match."""
    doc_pref = build_doc(
        "doc_pref",
        "Morning Coffee Habit",
        OKFType.PREFERENCE,
        OKFImportance.MEDIUM,
        ["coffee", "morning", "habit"],
        "User drinks espresso at 8am.",
    )
    doc_concept = build_doc(
        "doc_concept",
        "Theoretical Physics Definition",
        OKFType.CONCEPT,
        OKFImportance.HIGH,
        ["physics", "quantum"],
        "Quantum superposition explanation.",
    )

    slicer = DynamicSlicerEngine()

    # Under GREETING profile with generic greeting query
    greeting_result = await slicer.slice_documents(
        docs=[doc_concept, doc_pref],
        query="startup greeting",
        profile=SlicerProfile.GREETING,
        token_budget=1500,
    )
    assert greeting_result.selected_documents[0].id == "doc_pref"

    # Under CHAT profile with physics query
    chat_result = await slicer.slice_documents(
        docs=[doc_concept, doc_pref],
        query="Explain quantum physics",
        profile=SlicerProfile.CHAT,
        token_budget=1500,
    )
    assert chat_result.selected_documents[0].id == "doc_concept"


@pytest.mark.asyncio
async def test_slicer_slice_knowledge_interface_contract(
    storage_manager: Any,
    db_session: AsyncSession,
) -> None:
    """Verify slice_knowledge alias method conforms to PROJECT.md interface contract."""
    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    result = await slicer.slice_knowledge(
        user_id="user_test_alpha",
        query="What is my schedule?",
        token_budget=1500,
        profile="chat",
    )

    assert hasattr(result, "selected_documents")
    assert hasattr(result, "documents")
    assert hasattr(result, "formatted_context")
    assert hasattr(result, "total_tokens")


@pytest.mark.asyncio
async def test_slicer_db_fast_prefiltering(
    storage_manager: Any,
    db_session: AsyncSession,
) -> None:
    """Verify _fetch_via_db uses DB index to fetch documents."""
    user_id = "user_prefilter_test"
    doc_1 = build_doc("pref_1", "Pref 1", OKFType.PREFERENCE, OKFImportance.HIGH, ["p1"], "Body 1")
    await storage_manager.save_okf_file(user_id=user_id, doc=doc_1)

    rec = UserWikiIndex(
        user_id=user_id,
        okf_id="pref_1",
        title="Pref 1",
        type="preference",
        category="general",
        importance="high",
        tags=["p1"],
        file_path=f"storage/users/{user_id}/wikis/pref_1.md",
    )
    db_session.add(rec)
    await db_session.commit()

    slicer = DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)
    fetched_docs = await slicer._fetch_via_db(user_id=user_id, db_session=db_session)

    assert len(fetched_docs) == 1
    assert fetched_docs[0].metadata.id == "pref_1"
