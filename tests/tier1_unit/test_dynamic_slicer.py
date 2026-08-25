"""Tier 1 Unit Tests: OKF Dynamic Knowledge Slicer (F6).

Covers:
- Multi-factor scoring: importance weighting, tag/keyword matching, type priority, relations boost
- Token budget management & trimming: packing high-scoring documents within token budget
- Prompt context rendering: XML/Markdown format conforming to <user_knowledge_context>
- Edge cases: empty knowledge base, zero match queries, circular dependencies in relations.
"""

from __future__ import annotations

import pytest

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.slicer.engine import DynamicSlicerEngine

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
) -> OKFDocument:
    fm = OKFFrontmatter(
        id=doc_id,
        type=doc_type,
        title=title,
        tags=tags,
        importance=importance,
        source=OKFSource.MANUAL,
        relations=OKFRelations(
            depends_on=depends_on or [],
            related_to=related_to or [],
        ),
    )
    return OKFDocument(frontmatter=fm, body=body)


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
        build_doc("low_rule", "Low Priority Rule", OKFType.RULE, OKFImportance.LOW, ["rule"], "Low priority rule body"),
        build_doc("critical_rule", "Critical Security Rule", OKFType.RULE, OKFImportance.CRITICAL, ["rule"], "Critical security rule body"),
        build_doc("medium_rule", "Medium Rule", OKFType.RULE, OKFImportance.MEDIUM, ["rule"], "Medium rule body"),
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
    # Create 5 large documents
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
    # Set a tight budget that only fits ~1-2 documents
    result = await slicer.slice_documents(
        docs=docs,
        query="common_tag search query",
        token_budget=500,  # approximate budget
    )

    assert len(result.selected_documents) < len(docs)
    assert result.selected_documents[0].id == "doc_0"  # Highest importance prioritized
    assert result.total_estimated_tokens <= 600  # Within budget tolerance


@pytest.mark.asyncio
async def test_slicer_relations_expansion_and_cycle_prevention() -> None:
    """Verify that related_to and depends_on links are traversed and cycles are handled safely."""
    # Create cyclical graph: doc_A -> doc_B -> doc_A
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
