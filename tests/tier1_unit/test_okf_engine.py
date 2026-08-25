"""Tier 1 Unit Tests: OKF Engine, Parser, Serializer, Models & Validators.

Covers:
- F1: OKF Parser & Canonical Serializer (YAML Frontmatter + Markdown Body 2-layer format)
- F2: OKF Pydantic Models & Schema Validation (okf_version, id slug, types, sources,
      importance, relations, tags normalization, roundtrip fidelity, adversarial cases).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tars.core.okf.models import (
    OKFDocument,
    OKFFrontmatter,
    OKFImportance,
    OKFRelations,
    OKFSource,
    OKFType,
)
from tars.core.okf.parser import (
    OKFInvalidFrontmatterError,
    OKFMissingFieldError,
    OKFParserError,
    OKFValidationError,
    parse_okf_text,
)
from tars.core.okf.serializer import serialize_okf_document

# ============================================================================
# F1: OKF Parser Tests
# ============================================================================


def test_parse_valid_okf_document(sample_okf_text_valid: str) -> None:
    """Verify that a fully conforming OKF document is correctly parsed with all fields."""
    doc = parse_okf_text(sample_okf_text_valid)

    assert isinstance(doc, OKFDocument)
    assert doc.frontmatter.okf_version == "1.0"
    assert doc.frontmatter.id == "user_pref_001"
    assert doc.frontmatter.type == OKFType.PREFERENCE
    assert doc.frontmatter.title == "TARS Humor & Communication Rules"
    assert doc.frontmatter.category == "persona_settings"
    assert doc.frontmatter.tags == ["interstellar", "humor", "custom_rule"]
    assert doc.frontmatter.importance == OKFImportance.HIGH
    assert doc.frontmatter.source == OKFSource.AUTO_EXTRACTED
    assert doc.frontmatter.relations.depends_on == []
    assert doc.frontmatter.relations.related_to == ["core_tars_persona", "honesty_setting"]
    assert doc.frontmatter.created_at == datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC)
    assert doc.frontmatter.updated_at == datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC)

    # Body validation
    assert "# TARS Humor & Communication Rules" in doc.body
    assert "Maintain 90% humor setting" in doc.body


def test_parse_minimal_valid_okf_document() -> None:
    """Verify parsing when only mandatory fields are present (with defaults applied)."""
    raw_text = """---
id: "quick_note_01"
type: "concept"
title: "TARS Architecture"
source: "manual"
---
TARS uses a decoupled storage architecture.
"""
    doc = parse_okf_text(raw_text)

    assert doc.id == "quick_note_01"
    assert doc.type == OKFType.CONCEPT
    assert doc.title == "TARS Architecture"
    assert doc.frontmatter.source == OKFSource.MANUAL
    assert doc.frontmatter.okf_version == "1.0"
    assert doc.importance == OKFImportance.MEDIUM  # default
    assert doc.category is None  # default
    assert doc.tags == []  # default
    assert doc.frontmatter.relations.depends_on == []
    assert doc.frontmatter.relations.related_to == []
    assert "TARS uses a decoupled storage architecture." in doc.body.strip()


def test_parse_missing_frontmatter_delimiters_raises_error() -> None:
    """Verify that raw text without frontmatter delimiters ('---') raises OKFParserError."""
    raw_markdown = "# Plain Title\nJust plain markdown without YAML frontmatter."
    with pytest.raises((OKFInvalidFrontmatterError, OKFParserError)):
        parse_okf_text(raw_markdown)


def test_parse_unclosed_frontmatter_raises_error() -> None:
    """Verify that an unclosed YAML frontmatter block raises an error."""
    raw_text = """---
id: "unclosed_doc"
type: "rule"
title: "Missing Closing Tag"
source: "manual"
No closing triple dashes here...
"""
    with pytest.raises((OKFInvalidFrontmatterError, OKFParserError)):
        parse_okf_text(raw_text)


def test_parse_invalid_yaml_syntax_raises_error() -> None:
    """Verify that invalid YAML syntax within the frontmatter raises OKFInvalidFrontmatterError."""
    raw_text = """---
id: "bad_yaml"
type: "rule"
title: [unbalanced brackets : {
source: "manual"
---
Body text
"""
    with pytest.raises((OKFInvalidFrontmatterError, OKFParserError)):
        parse_okf_text(raw_text)


def test_parse_missing_mandatory_field_raises_error() -> None:
    """Verify that omitting mandatory fields (e.g., id or type) raises validation error."""
    missing_id_text = """---
type: "rule"
title: "No ID Specified"
source: "manual"
---
Some rule.
"""
    with pytest.raises((OKFValidationError, OKFMissingFieldError, ValidationError)):
        parse_okf_text(missing_id_text)


def test_parse_body_with_embedded_horizontal_rules() -> None:
    """Verify that markdown bodies containing internal '---' horizontal rules are preserved."""
    raw_text = """---
id: "doc_with_hrs"
type: "procedure"
title: "Procedure with Markdown Horizontal Rules"
source: "manual"
---
# Step 1: Initializing
Some preliminary content.

---

# Step 2: Intermediate Check
Another section separated by a horizontal rule.

---

# Step 3: Completion
Done.
"""
    doc = parse_okf_text(raw_text)
    assert doc.id == "doc_with_hrs"
    assert doc.type == OKFType.PROCEDURE
    assert "Step 1: Initializing" in doc.body
    assert "Step 2: Intermediate Check" in doc.body
    assert "Step 3: Completion" in doc.body
    assert doc.body.count("---") == 2


# ============================================================================
# F1: OKF Serializer Tests
# ============================================================================


def test_serialize_okf_document_roundtrip(sample_okf_doc: OKFDocument) -> None:
    """Verify serialize -> parse -> assert identical roundtrip fidelity."""
    serialized = serialize_okf_document(sample_okf_doc)
    assert serialized.startswith("---\n")
    assert "\n---\n" in serialized

    reparsed_doc = parse_okf_text(serialized)
    assert reparsed_doc.id == sample_okf_doc.id
    assert reparsed_doc.type == sample_okf_doc.type
    assert reparsed_doc.title == sample_okf_doc.title
    assert reparsed_doc.category == sample_okf_doc.category
    assert reparsed_doc.tags == sample_okf_doc.tags
    assert reparsed_doc.importance == sample_okf_doc.importance
    assert reparsed_doc.frontmatter.source == sample_okf_doc.frontmatter.source
    assert (
        reparsed_doc.frontmatter.relations.related_to
        == sample_okf_doc.frontmatter.relations.related_to
    )
    assert reparsed_doc.body.strip() == sample_okf_doc.body.strip()


def test_serialize_canonical_key_ordering() -> None:
    """Verify that serialized YAML frontmatter maintains predictable canonical key order."""
    frontmatter = OKFFrontmatter(
        okf_version="1.0",
        id="order_test_doc",
        type=OKFType.RULE,
        title="Key Order Test",
        category="testing",
        tags=["order", "canonical"],
        importance=OKFImportance.CRITICAL,
        source=OKFSource.SYSTEM,
        relations=OKFRelations(depends_on=["base_rule"], related_to=[]),
        created_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC),
    )
    doc = OKFDocument(metadata=frontmatter, content="# Rule Content\nDo not violate.")
    serialized = serialize_okf_document(doc)

    lines = serialized.splitlines()
    assert lines[0] == "---"
    # Verify core keys are present in expected relative order
    keys_found = [
        line.split(":")[0].strip() for line in lines if ":" in line and not line.startswith(" ")
    ]
    assert "okf_version" in keys_found
    assert "id" in keys_found
    assert "type" in keys_found
    assert "title" in keys_found
    assert keys_found.index("okf_version") < keys_found.index("id") < keys_found.index("type")


# ============================================================================
# F2: OKF Pydantic Models & Validator Tests
# ============================================================================


def test_okf_id_slug_validation() -> None:
    """Verify that document IDs adhere strictly to the slug format ^[a-zA-Z0-9_-]{1,128}$."""
    # Valid slugs
    for valid_slug in ["user_pref_001", "my-doc-123", "RULE_ALPHA_99", "simple"]:
        fm = OKFFrontmatter(
            id=valid_slug,
            type=OKFType.RULE,
            title="Valid Slug Test",
            source=OKFSource.MANUAL,
        )
        assert fm.id == valid_slug

    # Invalid slugs (spaces, slashes, special characters, empty)
    for invalid_slug in [
        "bad id with spaces",
        "path/traversal",
        "../escape",
        "bad@id",
        "",
        "a" * 129,
    ]:
        with pytest.raises((ValueError, ValidationError)):
            OKFFrontmatter(
                id=invalid_slug,
                type=OKFType.RULE,
                title="Invalid Slug Test",
                source=OKFSource.MANUAL,
            )


def test_okf_enum_coverage_all_values() -> None:
    """Verify that all OKFType, OKFImportance, and OKFSource enum members are supported."""
    expected_types = {"concept", "rule", "entity", "procedure", "preference"}
    actual_types = {t.value for t in OKFType}
    assert actual_types == expected_types

    expected_importances = {"low", "medium", "high", "critical"}
    actual_importances = {i.value for i in OKFImportance}
    assert actual_importances == expected_importances

    expected_sources = {"manual", "auto_extracted", "system"}
    actual_sources = {s.value for s in OKFSource}
    assert actual_sources == expected_sources


def test_okf_tags_normalization_and_deduplication() -> None:
    """Verify that tags are trimmed, lowercased, and deduplicated while preserving order."""
    fm = OKFFrontmatter(
        id="tag_norm_doc",
        type=OKFType.CONCEPT,
        title="Tag Normalization",
        tags=["  Python  ", "PYTHON", "FastAPI", "fastapi", "ai_agent"],
        source=OKFSource.MANUAL,
    )
    assert fm.tags == ["python", "fastapi", "ai_agent"]


def test_okf_relations_model_validation() -> None:
    """Verify OKFRelations model handles empty lists and list cleaning properly."""
    rel = OKFRelations(
        depends_on=["doc_a", "  doc_b  ", ""],
        related_to=["doc_c"],
    )
    assert rel.depends_on == ["doc_a", "doc_b"]
    assert rel.related_to == ["doc_c"]


def test_adversarial_malformed_frontmatter_types() -> None:
    """Verify that invalid enum strings or non-string titles raise Pydantic validation errors."""
    raw_invalid_type = """---
id: "bad_type_doc"
type: "invalid_type_enum"
title: "Bad Type"
source: "manual"
---
Body
"""
    with pytest.raises((OKFValidationError, ValidationError, ValueError)):
        parse_okf_text(raw_invalid_type)

    raw_invalid_importance = """---
id: "bad_imp_doc"
type: "concept"
title: "Bad Importance"
importance: "super_ultra_high"
source: "manual"
---
Body
"""
    with pytest.raises((OKFValidationError, ValidationError, ValueError)):
        parse_okf_text(raw_invalid_importance)
