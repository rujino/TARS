"""Tier-1 Adversarial & Stress Verification Test Suite for Milestone 1.

Covers:
- OKF parser/serializer edge cases: zero-byte, nested YAML, emojis, horizontal rules, massive tags.
- StorageManager security: path traversal vectors, tenant isolation, concurrent writes, simulated I/O errors.
- Dynamic Slicer resilience: cyclic dependency graphs (A->B->C->A), strict token budget overflows.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tars.core.okf.errors import (
    OKFInvalidFrontmatterError,
    OKFValidationError,
    OKFVersionError,
)
from tars.core.okf.models import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFRelations,
    OKFType,
)
from tars.core.okf.parser import parse_okf_text
from tars.core.okf.serializer import serialize_okf_document
from tars.core.okf.validator import (
    validate_okf_document,
    validate_okf_semantic_relations,
)
from tars.slicer.engine import (
    DynamicSlicerEngine,
    HeuristicTokenCounter,
    SlicerWeights,
)
from tars.storage.manager import (
    FileStorageManager,
    StorageIOError,
    StoragePathTraversalError,
    StorageSecurityError,
)

# ============================================================================
# 1. OKF Parser & Serializer Adversarial Tests
# ============================================================================


class TestOKFParserAdversarial:
    """Stress-testing OKF parser and serializer against adversarial inputs."""

    @pytest.mark.parametrize(
        "empty_input",
        [
            "",
            "   \n\n\t  \r\n",
            "\ufeff",
            "\ufeff   \n\t",
        ],
    )
    def test_parse_zero_byte_and_whitespace_inputs(self, empty_input: str) -> None:
        """Zero-byte or whitespace-only files must raise OKFInvalidFrontmatterError."""
        with pytest.raises(OKFInvalidFrontmatterError):
            parse_okf_text(empty_input)

    @pytest.mark.parametrize(
        "unclosed_input",
        [
            "---\nid: doc1\ntype: concept\ntitle: Doc 1\n",
            "---\nid: doc1\ntype: concept\ntitle: Doc 1\n# Body without closing",
            "id: doc1\ntype: concept\ntitle: Doc 1\n---\nBody",
            "--- \t \n\nid: doc1\ntype: concept\ntitle: Doc 1",
        ],
    )
    def test_parse_missing_or_unclosed_frontmatter(self, unclosed_input: str) -> None:
        """Missing opening or closing delimiters must be rejected."""
        with pytest.raises(OKFInvalidFrontmatterError):
            parse_okf_text(unclosed_input)

    def test_parse_yaml_list_root_rejected(self) -> None:
        """Frontmatter that parses to a list instead of a dict must raise OKFInvalidFrontmatterError."""
        raw = """---
- item1
- item2
- item3
---
Body text
"""
        with pytest.raises(OKFInvalidFrontmatterError) as exc_info:
            parse_okf_text(raw)
        assert "YAML dictionary/mapping" in str(exc_info.value)

    def test_parse_yaml_unsafe_object_execution_rejected(self) -> None:
        """Arbitrary python object constructors must be rejected by safe_load."""
        raw = """---
!!python/object/apply:os.system ["echo pwned"]
---
Body
"""
        with pytest.raises(OKFInvalidFrontmatterError):
            parse_okf_text(raw)

    def test_parse_deeply_nested_extra_yaml_fields(self) -> None:
        """Deeply nested arbitrary YAML mappings must not crash the parser (extra fields ignored)."""
        raw = """---
okf_version: "1.0"
id: deeply-nested-doc
type: concept
title: Deep Nested Structure
extra_data:
  level1:
    level2:
      level3:
        level4:
          key: "deep_value"
          numbers: [1, 2, 3, 4, 5]
---
# Deeply Nested Test
Content is preserved.
"""
        doc = parse_okf_text(raw)
        assert doc.id == "deeply-nested-doc"
        assert doc.title == "Deep Nested Structure"
        assert doc.content.strip() == "# Deeply Nested Test\nContent is preserved."

    def test_unicode_emojis_and_multilingual_roundtrip(self) -> None:
        """Complex multilingual UTF-8 text and emojis must roundtrip without corruption."""
        title = "🪐 TARS OKF 엔진 🚀 & AI 지식 베이스 🤖 (日本語, العربية, 🐍)"
        content = """# 🚀 TARS Multilingual & Emoji Test

- **수학 기호**: ∀x ∈ ℝ: x² ≥ 0, ∫₀^∞ e^{-x} dx = 1
- **한글 유니코드**: 가나다라마바사 아자차카타파하 뷁뷄믜
- **일본어 & 한자**: 東京, 宇宙空間, アシスタント
- **아랍어 (RTL)**: مرحباً بكم في نظام المعرفة
- **이모지 & ZWJ**: 👨‍👩‍👧‍👦, 🧑‍🚀, 🛰️, 🧪, 💡, 🔥, ⚡
"""
        tags = ["🚀tars", "🏷️ai_지식", "日本語タグ", "مرحبا", "🔥special"]

        doc = OKFDocument(
            metadata=OKFMetadata(
                id="multilingual-unicode-test",
                type=OKFType.CONCEPT,
                title=title,
                tags=tags,
                importance=OKFImportance.HIGH,
            ),
            content=content,
        )

        serialized = serialize_okf_document(doc)
        assert "🪐" in serialized
        assert "مرحبا" in serialized
        assert "\\u" not in serialized  # Ensure allow_unicode=True is active

        reparsed = parse_okf_text(serialized)
        assert reparsed.title == title
        assert reparsed.content.strip() == content.strip()
        assert "🚀tars" in reparsed.tags
        assert "日本語タグ" in reparsed.tags

    def test_markdown_embedded_horizontal_rules_stress(self) -> None:
        """Multiple consecutive and trailing horizontal rules ('---') in markdown body must be preserved."""
        raw = """---
okf_version: "1.0"
id: hr-stress-test
type: rule
title: Horizontal Rules Stress Test
---
# Section 1
Content before divider.

---

# Section 2
Content between dividers.

---
---
---

# Section 3
Trailing dividers.

---"""
        doc = parse_okf_text(raw)
        assert doc.id == "hr-stress-test"
        assert "# Section 1" in doc.content
        assert "# Section 2" in doc.content
        assert "# Section 3" in doc.content
        # Verify horizontal rules survived
        assert "---" in doc.content

    def test_massive_tags_list_deduplication_and_normalization(self) -> None:
        """Massive tag lists (5,000 items) must be normalized to lowercase and deduplicated."""
        raw_tags = [f"Tag_{i % 100}" for i in range(5000)]  # 100 unique tags repeated 50 times
        raw_tags.extend(["  SPACED_TAG  ", "DUPLICATE", "duplicate", "Duplicate"])

        meta = OKFMetadata(
            id="massive-tags-doc",
            type=OKFType.ENTITY,
            title="Massive Tags Test",
            tags=raw_tags,
        )

        assert len(meta.tags) <= 102
        assert "spaced_tag" in meta.tags
        assert "duplicate" in meta.tags
        assert meta.tags.count("duplicate") == 1

    def test_title_and_id_boundary_validations(self) -> None:
        """Title length > 256 or invalid ID slugs must raise validation errors."""
        # 1. Title exceeding 256 characters
        long_title = "A" * 257
        with pytest.raises(OKFValidationError):
            parse_okf_text(f"""---
id: valid-id
type: concept
title: "{long_title}"
---
Body
""")

        # 2. Empty title
        with pytest.raises(OKFValidationError):
            parse_okf_text("""---
id: valid-id
type: concept
title: "   "
---
Body
""")

        # 3. Invalid ID slugs with forbidden characters
        invalid_ids = [
            "id with space",
            "id/with/slash",
            "id@special!",
            "id.with.dot",
            "id#hash",
            "a" * 129,
        ]
        for bad_id in invalid_ids:
            with pytest.raises(OKFValidationError):
                parse_okf_text(f"""---
id: "{bad_id}"
type: concept
title: Valid Title
---
Body
""")

    def test_semantic_validator_rules(self) -> None:
        """Semantic validator checks self-references, timestamp sanity, and versioning."""
        # 1. Self-reference in depends_on
        self_dep_doc = OKFDocument(
            metadata=OKFMetadata(
                id="self-dep",
                type=OKFType.RULE,
                title="Self Dep",
                relations=OKFRelations(depends_on=["self-dep"]),
            )
        )
        assert validate_okf_document(self_dep_doc, raise_on_error=False) is False
        with pytest.raises(OKFValidationError) as exc:
            validate_okf_document(self_dep_doc, raise_on_error=True)
        assert "cannot depend on itself" in str(exc.value)

        # 2. created_at > updated_at
        now = datetime.now(UTC)
        invalid_time_doc = OKFDocument(
            metadata=OKFMetadata(
                id="time-travel",
                type=OKFType.CONCEPT,
                title="Time Travel",
                created_at=now + timedelta(days=10),
                updated_at=now,
            )
        )
        assert validate_okf_document(invalid_time_doc, raise_on_error=False) is False

        # 3. Incompatible version
        unsupported_ver_doc = OKFDocument(
            metadata=OKFMetadata(
                okf_version="99.0",
                id="future-doc",
                type=OKFType.CONCEPT,
                title="Future Doc",
            )
        )
        with pytest.raises(OKFVersionError):
            validate_okf_document(unsupported_ver_doc, raise_on_error=True)


# ============================================================================
# 2. FileStorageManager Security & Stress Tests
# ============================================================================


class TestStorageManagerSecurityAndStress:
    """Stress-testing storage manager against path traversal, concurrency, and I/O failures."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorageManager:
        return FileStorageManager(base_storage_dir=tmp_path)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "malicious_user_id",
        [
            "../../../../etc/passwd",
            "C:\\Windows\\System32",
            "user/../other_user",
            "user/subdir",
            "user\\backslash",
            "user\x00null",
            ".",
            "..",
            "/root",
            "~/.ssh",
            "user name with spaces",
            "user@domain.com",
        ],
    )
    async def test_path_traversal_user_id_rejected(
        self, storage: FileStorageManager, malicious_user_id: str
    ) -> None:
        """Malicious user_id inputs must be blocked with StorageSecurityError or StoragePathTraversalError."""
        doc = OKFDocument(
            metadata=OKFMetadata(
                id="doc1",
                type=OKFType.CONCEPT,
                title="Title",
            )
        )

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.save_okf_file(malicious_user_id, doc)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.read_okf_file(malicious_user_id, "doc1")

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.list_okf_files(malicious_user_id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "malicious_okf_id",
        [
            "../../../../etc/passwd",
            "C:\\Windows\\System32",
            "doc/../escaped",
            "doc/subdir",
            "doc\\backslash",
            "doc\x00null",
            ".",
            "..",
            "/absolute/path",
            "doc.md/../../escaped",
        ],
    )
    async def test_path_traversal_okf_id_rejected(
        self, storage: FileStorageManager, malicious_okf_id: str
    ) -> None:
        """Malicious okf_id inputs must be blocked with StorageSecurityError or StoragePathTraversalError."""
        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.read_okf_file("valid_user", malicious_okf_id)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.delete_okf_file("valid_user", malicious_okf_id)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.exists_okf_file("valid_user", malicious_okf_id)

        with pytest.raises((StorageSecurityError, StoragePathTraversalError)):
            await storage.get_file_hash("valid_user", malicious_okf_id)

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_same_file_integrity(
        self, storage: FileStorageManager
    ) -> None:
        """50 concurrent writes to the EXACT SAME file must remain atomic and uncorrupted."""
        user_id = "stress_user_1"
        okf_id = "concurrent_target"
        num_tasks = 50

        async def write_version(idx: int) -> Path:
            doc = OKFDocument(
                metadata=OKFMetadata(
                    id=okf_id,
                    type=OKFType.PROCEDURE,
                    title=f"Concurrent Write Version {idx}",
                ),
                content=f"Payload version content index: {idx}\nTimestamp: {datetime.now(UTC).isoformat()}",
            )
            return await storage.save_okf_file(user_id, doc)

        # Run 50 concurrent atomic writes
        results = await asyncio.gather(*(write_version(i) for i in range(num_tasks)))
        assert len(results) == num_tasks

        # Verify that final file is valid OKF and readable
        final_doc = await storage.read_okf_file(user_id, okf_id)
        assert final_doc.id == okf_id
        assert "Payload version content index:" in final_doc.content

        # Verify no orphan temp files remain
        user_dir = storage.get_user_wikis_dir(user_id)
        tmp_files = list(user_dir.glob(".tmp.*"))
        assert len(tmp_files) == 0, f"Found leaked temp files: {tmp_files}"

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_distinct_files(
        self, storage: FileStorageManager
    ) -> None:
        """50 concurrent writes to DISTINCT files for the same user."""
        user_id = "stress_user_2"
        num_docs = 50

        async def write_doc(idx: int) -> Path:
            doc = OKFDocument(
                metadata=OKFMetadata(
                    id=f"doc_{idx:03d}",
                    type=OKFType.ENTITY,
                    title=f"Document Number {idx}",
                    tags=[f"tag_{idx}"],
                ),
                content=f"Distinct content for doc {idx}",
            )
            return await storage.save_okf_file(user_id, doc)

        await asyncio.gather(*(write_doc(i) for i in range(num_docs)))

        # List all documents
        listed_docs = await storage.list_okf_files(user_id)
        assert len(listed_docs) == num_docs
        listed_ids = {d.id for d in listed_docs}
        for i in range(num_docs):
            assert f"doc_{i:03d}" in listed_ids

    @pytest.mark.asyncio
    async def test_simulated_io_error_during_save_cleans_up_tmp(
        self, storage: FileStorageManager
    ) -> None:
        """Simulated I/O failure during file save must raise StorageIOError and clean up temporary files."""
        user_id = "io_error_user"
        doc = OKFDocument(
            metadata=OKFMetadata(
                id="io_fail_doc",
                type=OKFType.CONCEPT,
                title="IO Fail Doc",
            ),
            content="Some body",
        )

        with patch("os.replace", side_effect=OSError("Simulated disk write failure")):
            with pytest.raises(StorageIOError) as exc_info:
                await storage.save_okf_file(user_id, doc)
            assert "Failed to atomically write OKF file" in str(exc_info.value)

        # Verify no orphan .tmp.* files were left behind
        user_dir = storage.get_user_wikis_dir(user_id)
        if user_dir.exists():
            tmp_files = list(user_dir.glob(".tmp.*"))
            assert len(tmp_files) == 0, f"Leaked tmp files: {tmp_files}"


# ============================================================================
# 3. Dynamic Slicer Graph & Budget Tests
# ============================================================================


class TestDynamicSlicerAdversarial:
    """Stress-testing Dynamic Slicer with cyclic graphs and strict token budget overflows."""

    @pytest.fixture
    def slicer(self) -> DynamicSlicerEngine:
        return DynamicSlicerEngine(token_counter=HeuristicTokenCounter(), weights=SlicerWeights())

    @pytest.mark.asyncio
    async def test_cyclic_relation_graph_3_node_ring(
        self, slicer: DynamicSlicerEngine
    ) -> None:
        """3-node cycle: A -> B -> C -> A. Slicer must expand relations without infinite loop."""
        doc_a = OKFDocument(
            metadata=OKFMetadata(
                id="node_a",
                type=OKFType.CONCEPT,
                title="Node A Root Knowledge",
                tags=["target"],
                relations=OKFRelations(depends_on=["node_b"]),
            ),
            content="Content of Node A",
        )
        doc_b = OKFDocument(
            metadata=OKFMetadata(
                id="node_b",
                type=OKFType.CONCEPT,
                title="Node B Intermediate",
                relations=OKFRelations(depends_on=["node_c"]),
            ),
            content="Content of Node B",
        )
        doc_c = OKFDocument(
            metadata=OKFMetadata(
                id="node_c",
                type=OKFType.CONCEPT,
                title="Node C Cyclic Return",
                relations=OKFRelations(depends_on=["node_a"]),
            ),
            content="Content of Node C",
        )

        # 1. Test validator detects the cycle
        assert validate_okf_semantic_relations([doc_a, doc_b, doc_c], raise_on_error=False) is False
        with pytest.raises(OKFValidationError) as exc:
            validate_okf_semantic_relations([doc_a, doc_b, doc_c], raise_on_error=True)
        assert "Circular dependency detected" in str(exc.value)

        # 2. Test slicer handles cyclic docs safely and halts cleanly
        result = await slicer.slice_documents(
            docs=[doc_a, doc_b, doc_c],
            query="target",
            token_budget=1000,
        )
        assert len(result.selected_documents) == 3
        # Check no duplicated IDs
        selected_ids = [d.id for d in result.selected_documents]
        assert len(selected_ids) == len(set(selected_ids))

    @pytest.mark.asyncio
    async def test_10_node_circular_ring_graph(
        self, slicer: DynamicSlicerEngine
    ) -> None:
        """10-node cycle: N0 -> N1 -> N2 -> ... -> N9 -> N0."""
        n = 10
        docs = [
            OKFDocument(
                metadata=OKFMetadata(
                    id=f"ring_node_{i:02d}",
                    type=OKFType.CONCEPT,
                    title=f"Ring Node {i}",
                    tags=["ring_seed"] if i == 0 else [],
                    relations=OKFRelations(
                        depends_on=[f"ring_node_{(i + 1) % n:02d}"],
                        related_to=[f"ring_node_{(i - 1) % n:02d}"],
                    ),
                ),
                content=f"Content payload of ring node {i}",
            )
            for i in range(n)
        ]

        result = await slicer.slice_documents(
            docs=docs,
            query="ring_seed",
            token_budget=2000,
        )
        selected_ids = [d.id for d in result.selected_documents]
        assert len(selected_ids) <= n
        assert len(selected_ids) == len(set(selected_ids))  # No duplicates

    @pytest.mark.asyncio
    async def test_strict_token_budget_massive_document_truncation(
        self, slicer: DynamicSlicerEngine
    ) -> None:
        """Massive 10,000-word document with tiny token budget (50 tokens) must be truncated safely."""
        massive_text = "TARS autonomous AI robot knowledge base entry. " * 500  # ~25,000 chars

        doc = OKFDocument(
            metadata=OKFMetadata(
                id="massive_doc",
                type=OKFType.RULE,
                title="Massive Knowledge Entry",
                importance=OKFImportance.CRITICAL,
                tags=["critical"],
            ),
            content=massive_text,
        )

        result = await slicer.slice_documents(
            docs=[doc],
            query="critical",
            token_budget=60,
        )

        assert len(result.selected_documents) == 1
        truncated_doc = result.selected_documents[0]
        assert "... [truncated]" in truncated_doc.content
        assert len(truncated_doc.content) < len(massive_text)
        assert result.total_estimated_tokens > 0

    @pytest.mark.asyncio
    async def test_token_budget_zero_and_negative_degradation(
        self, slicer: DynamicSlicerEngine
    ) -> None:
        """Zero or negative token budget must degrade gracefully without crashing."""
        doc = OKFDocument(
            metadata=OKFMetadata(
                id="doc_normal",
                type=OKFType.CONCEPT,
                title="Normal Doc",
            ),
            content="Small content",
        )

        result_zero = await slicer.slice_documents(docs=[doc], token_budget=0)
        assert len(result_zero.selected_documents) <= 1

        result_neg = await slicer.slice_documents(docs=[doc], token_budget=-50)
        assert len(result_neg.selected_documents) <= 1

    @pytest.mark.asyncio
    async def test_50_documents_ranked_packing_under_budget(
        self, slicer: DynamicSlicerEngine
    ) -> None:
        """50 ranked documents packed under a 300-token budget. Higher ranked items must be chosen first."""
        docs: list[OKFDocument] = []
        for i in range(50):
            importance = (
                OKFImportance.CRITICAL
                if i < 5
                else OKFImportance.HIGH
                if i < 15
                else OKFImportance.LOW
            )
            doc_type = OKFType.RULE if i < 5 else OKFType.CONCEPT
            docs.append(
                OKFDocument(
                    metadata=OKFMetadata(
                        id=f"doc_ranked_{i:02d}",
                        type=doc_type,
                        importance=importance,
                        title=f"Ranked Document {i}",
                        tags=["query_match"] if i < 3 else [],
                    ),
                    content=f"Standard content body line for document {i}. Important knowledge.",
                )
            )

        result = await slicer.slice_documents(
            docs=docs,
            query="query_match",
            token_budget=200,
        )

        # Budget is 200 tokens: should fit several top documents but not all 50
        assert 1 <= len(result.selected_documents) < 50
        # The top matched documents must be selected
        top_ids = [d.id for d in result.selected_documents]
        assert "doc_ranked_00" in top_ids or "doc_ranked_01" in top_ids
