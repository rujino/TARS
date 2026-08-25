"""TARS Dynamic Slicer Engine for multi-factor ranking, relation expansion, and token budget packing."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import OKFDocument, OKFImportance, OKFMetadata, OKFType

logger = logging.getLogger("tars.slicer")

TOKEN_SPLIT_REGEX = re.compile(r"[\s,._\-\[\]\(\)\{\}\"\'/\\;:]+")


@runtime_checkable
class ITokenCounter(Protocol):
    """Protocol defining token counting contract."""

    def count_tokens(self, text: str) -> int:
        """Count or estimate the number of tokens in the provided text string."""
        ...


class HeuristicTokenCounter:
    """High-performance heuristic token counter optimized for CJK and ASCII text.

    Estimation rule:
    - ASCII / alphanumeric / symbols: ~4 chars per token.
    - CJK / Hangul / East Asian wide chars: ~1.5 chars per token.
    """

    __slots__ = ()

    def count_tokens(self, text: str) -> int:
        """Calculate estimated token count for text."""
        if not text:
            return 0

        cjk_count = 0
        ascii_count = 0

        for char in text:
            code = ord(char)
            # Hangul Jamo, Compatibility Jamo, Hangul Syllables, CJK Ideographs
            if (
                0x1100 <= code <= 0x11FF
                or 0x3130 <= code <= 0x318F
                or 0xAC00 <= code <= 0xD7AF
                or 0x2E80 <= code <= 0x9FFF
                or 0xF900 <= code <= 0xFAFF
            ):
                cjk_count += 1
            else:
                ascii_count += 1

        estimated = (ascii_count / 4.0) + (cjk_count / 1.5)
        return max(1, math.ceil(estimated))


class SlicerWeights(BaseModel):
    """Configuration weights for multi-factor scoring formula."""

    model_config = ConfigDict(frozen=True)

    weight_importance: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_match: float = Field(default=0.40, ge=0.0, le=1.0)
    weight_type: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_recency: float = Field(default=0.10, ge=0.0, le=1.0)


IMPORTANCE_SCORE_MAP: Mapping[OKFImportance, float] = {
    OKFImportance.CRITICAL: 1.00,
    OKFImportance.HIGH: 0.75,
    OKFImportance.MEDIUM: 0.50,
    OKFImportance.LOW: 0.20,
}

TYPE_SCORE_MAP: Mapping[OKFType, float] = {
    OKFType.RULE: 1.00,
    OKFType.PREFERENCE: 0.90,
    OKFType.PROCEDURE: 0.70,
    OKFType.ENTITY: 0.50,
    OKFType.CONCEPT: 0.40,
}


def tokenize_text(text: str) -> set[str]:
    """Tokenize and normalize text into unique lowercase tokens."""
    if not text:
        return set()
    raw_tokens = TOKEN_SPLIT_REGEX.split(text.lower())
    return {t.strip() for t in raw_tokens if len(t.strip()) > 0}


def calculate_match_score(
    metadata: OKFMetadata,
    query_tokens: set[str],
    active_tags: set[str],
) -> float:
    """Calculate query keyword and tag matching score in range [0.0, 1.0]."""
    if not query_tokens and not active_tags:
        return 0.0

    doc_tags = {tag.lower().strip() for tag in metadata.tags if tag.strip()}

    # 1. Active tags overlap
    tag_score = 0.0
    if active_tags:
        overlap = len(active_tags.intersection(doc_tags))
        tag_score = overlap / max(1, len(active_tags))

    # 2. Query tokens vs doc tags
    q_tag_score = 0.0
    if query_tokens and doc_tags:
        overlap = len(query_tokens.intersection(doc_tags))
        q_tag_score = overlap / max(1, len(doc_tags))

    # 3. Query tokens vs title, category, id
    q_text_score = 0.0
    if query_tokens:
        text_target = f"{metadata.title} {metadata.category or ''} {metadata.id}".lower()
        title_tokens = tokenize_text(text_target)
        overlap = len(query_tokens.intersection(title_tokens))
        q_text_score = overlap / max(1, len(title_tokens))

    combined = (0.45 * tag_score) + (0.35 * q_tag_score) + (0.20 * q_text_score)
    return min(1.0, combined)


def calculate_recency_score(updated_at: datetime) -> float:
    """Calculate temporal freshness score using exponential decay."""
    now = datetime.now(UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    delta = (now - updated_at).total_seconds()
    days = max(0.0, delta / 86400.0)
    # Decay constant: half-life ~ 30 days
    return max(0.05, math.exp(-days / 30.0))


def compute_document_score(
    metadata: OKFMetadata,
    query_tokens: set[str],
    active_tags: set[str],
    weights: SlicerWeights,
) -> float:
    """Compute combined multi-factor score for a single OKF document."""
    imp_score = IMPORTANCE_SCORE_MAP.get(metadata.importance, 0.50)
    match_score = calculate_match_score(metadata, query_tokens, active_tags)
    type_score = TYPE_SCORE_MAP.get(metadata.type, 0.50)
    rec_score = calculate_recency_score(metadata.updated_at)

    total = (
        (weights.weight_importance * imp_score)
        + (weights.weight_match * match_score)
        + (weights.weight_type * type_score)
        + (weights.weight_recency * rec_score)
    )
    return min(1.0, max(0.0, total))


def format_knowledge_context_xml(docs: Sequence[OKFDocument]) -> str:
    """Format a sequence of OKFDocument instances into a clean XML block."""
    if not docs:
        return "<user_knowledge_context>\n</user_knowledge_context>"

    items: list[str] = ["<user_knowledge_context>"]
    for doc in docs:
        meta = doc.metadata
        item_text = (
            f"[OKF: {meta.id} | Type: {meta.type.value} | Importance: {meta.importance.value}]\n"
            f"# {meta.title}\n"
            f"{doc.content.strip()}"
        )
        items.append(item_text)
    items.append("</user_knowledge_context>")

    return "\n\n".join(items)


def format_knowledge_context_markdown(docs: Sequence[OKFDocument]) -> str:
    """Format a sequence of OKFDocument instances into a markdown section block."""
    if not docs:
        return ""

    blocks: list[str] = ["## Relevant Knowledge Context\n"]
    for doc in docs:
        meta = doc.metadata
        blocks.append(
            f"### [{meta.type.value.upper()}] {meta.title} (id: {meta.id})\n{doc.content.strip()}\n"
        )
    return "\n".join(blocks)


class SlicedContextResult(BaseModel):
    """Result structure containing sliced documents and prompt context metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    selected_documents: list[OKFDocument] = Field(default_factory=list)
    total_estimated_tokens: int = Field(default=0)
    formatted_context: str = Field(default="")
    scores: dict[str, float] = Field(default_factory=dict)

    @property
    def documents(self) -> list[OKFDocument]:
        """Alias for selected_documents."""
        return self.selected_documents

    @property
    def total_tokens(self) -> int:
        """Alias for total_estimated_tokens."""
        return self.total_estimated_tokens


# Alias for backward and blueprint compatibility
SlicedKnowledgeResult = SlicedContextResult


class DynamicSlicerEngine:
    """Production-grade Dynamic Knowledge Slicer Engine."""

    def __init__(
        self,
        storage_manager: Any = None,
        token_counter: ITokenCounter | None = None,
        weights: SlicerWeights | None = None,
        db_session: AsyncSession | None = None,
    ) -> None:
        self.storage_manager = storage_manager
        self.token_counter: ITokenCounter = token_counter or HeuristicTokenCounter()
        self.weights: SlicerWeights = weights or SlicerWeights()
        self._db_session = db_session

    def render_context_xml(self, docs: Sequence[OKFDocument]) -> str:
        """Render knowledge context in user knowledge context XML wrapper."""
        if not docs:
            return ""

        blocks: list[str] = ["<user_knowledge_context>"]
        for doc in docs:
            meta = doc.metadata
            block = (
                f"[OKF: {meta.id} | Type: {meta.type.value} | Importance: {meta.importance.value}]\n"
                f"# {meta.title}\n"
                f"{doc.content.strip()}"
            )
            blocks.append(block)
        blocks.append("</user_knowledge_context>")
        return "\n\n".join(blocks)

    async def slice_documents(
        self,
        docs: Sequence[OKFDocument],
        query: str = "",
        active_tags: list[str] | None = None,
        token_budget: int = 1500,
    ) -> SlicedContextResult:
        """Slice a provided collection of OKF documents within token budget."""
        if not docs:
            return SlicedContextResult(
                selected_documents=[],
                total_estimated_tokens=0,
                formatted_context="",
                scores={},
            )

        query_tokens = tokenize_text(query)
        norm_active_tags = {t.lower().strip() for t in (active_tags or []) if t.strip()}

        # 1. Base multi-factor scoring
        doc_map: dict[str, OKFDocument] = {doc.metadata.id: doc for doc in docs}
        score_map: dict[str, float] = {}

        for okf_id, doc in doc_map.items():
            score = compute_document_score(
                metadata=doc.metadata,
                query_tokens=query_tokens,
                active_tags=norm_active_tags,
                weights=self.weights,
            )
            score_map[okf_id] = score

        # 2. 1-Hop relation expansion & boosting with cycle prevention
        score_map = self._expand_relations(doc_map, score_map)

        # 3. Sort ranked documents
        sorted_ids = sorted(
            score_map.keys(),
            key=lambda okf_id: (
                score_map[okf_id],
                IMPORTANCE_SCORE_MAP.get(doc_map[okf_id].metadata.importance, 0.5),
            ),
            reverse=True,
        )

        # 4. Pack within token budget
        selected_docs: list[OKFDocument] = []
        accumulated_tokens = 0
        wrapper_overhead = 30
        available_budget = max(50, token_budget - wrapper_overhead)

        for okf_id in sorted_ids:
            doc = doc_map[okf_id]
            doc_rendered = (
                f"[OKF: {doc.metadata.id} | Type: {doc.metadata.type.value} | Importance: {doc.metadata.importance.value}]\n"
                f"# {doc.metadata.title}\n"
                f"{doc.content.strip()}"
            )
            doc_tokens = self.token_counter.count_tokens(doc_rendered)

            if accumulated_tokens + doc_tokens <= available_budget:
                selected_docs.append(doc)
                accumulated_tokens += doc_tokens
            else:
                # If no doc packed yet and this single doc exceeds budget, truncate it
                if not selected_docs:
                    truncated_content = self._truncate_text_to_budget(
                        doc.content, available_budget - 30
                    )
                    truncated_doc = OKFDocument(
                        metadata=doc.metadata,
                        content=truncated_content + "\n... [truncated]",
                    )
                    selected_docs.append(truncated_doc)
                    accumulated_tokens = available_budget
                break

        formatted_xml = self.render_context_xml(selected_docs)
        total_tokens = self.token_counter.count_tokens(formatted_xml)

        return SlicedContextResult(
            selected_documents=selected_docs,
            formatted_context=formatted_xml,
            total_estimated_tokens=total_tokens,
            scores={doc.metadata.id: score_map.get(doc.metadata.id, 0.0) for doc in selected_docs},
        )

    async def slice_context(
        self,
        user_id: str,
        query: str = "",
        active_tags: list[str] | None = None,
        token_budget: int = 1500,
        db_session: AsyncSession | None = None,
    ) -> list[OKFDocument]:
        """Slice and return most relevant OKF documents for a user from storage or DB index.

        Conforms to PROJECT.md interface contract.
        """
        session_to_use = db_session if db_session is not None else self._db_session
        if session_to_use is not None and self.storage_manager is not None:
            all_docs = await self._fetch_via_db(user_id, session_to_use)

        if not all_docs and self.storage_manager is not None:
            try:
                all_docs = await self.storage_manager.list_okf_files(user_id)
            except Exception as e:
                logger.warning("Failed to list files from storage for user %s: %s", user_id, e)
                all_docs = []

        result = await self.slice_documents(
            docs=all_docs,
            query=query,
            active_tags=active_tags,
            token_budget=token_budget,
        )
        return result.selected_documents

    def _expand_relations(
        self,
        doc_map: dict[str, OKFDocument],
        score_map: dict[str, float],
    ) -> dict[str, float]:
        """Expand 1-hop depends_on and related_to relations with cycle detection."""
        updated_scores = dict(score_map)
        visited: set[str] = set()

        # Identify top seeds (score > 0.35 or top 5)
        seed_candidates = sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:5]

        for seed_id, seed_score in seed_candidates:
            if seed_id in visited or seed_id not in doc_map:
                continue
            visited.add(seed_id)
            seed_doc = doc_map[seed_id]
            relations = seed_doc.metadata.relations

            # 1. depends_on: Essential dependency promotion
            for dep_id in relations.depends_on:
                if dep_id in doc_map and dep_id not in visited:
                    current_dep_score = updated_scores.get(dep_id, 0.0)
                    promoted_score = max(current_dep_score, seed_score * 0.95)
                    updated_scores[dep_id] = min(1.0, promoted_score)

            # 2. related_to: Associative boost (+0.15)
            for rel_id in relations.related_to:
                if rel_id in doc_map and rel_id not in visited:
                    current_rel_score = updated_scores.get(rel_id, 0.0)
                    boosted_score = current_rel_score + 0.15
                    updated_scores[rel_id] = min(1.0, boosted_score)

        return updated_scores

    async def _fetch_via_db(
        self,
        user_id: str,
        db_session: AsyncSession,
    ) -> list[OKFDocument]:
        """Pre-query DB metadata index for fast candidate retrieval."""
        try:
            from tars.db.models import UserWikiIndex

            stmt = select(UserWikiIndex.okf_id).where(UserWikiIndex.user_id == user_id)
            result = await db_session.execute(stmt)
            okf_ids = [row[0] for row in result.all()]

            docs: list[OKFDocument] = []
            for okf_id in okf_ids:
                try:
                    doc = await self.storage_manager.read_okf_file(user_id, okf_id)
                    docs.append(doc)
                except Exception as e:
                    logger.debug("Could not read file for %s/%s: %s", user_id, okf_id, e)
            return docs
        except Exception as err:
            logger.warning("DB pre-query failed for user %s: %s", user_id, err)
            return []

    def _truncate_text_to_budget(self, text: str, max_tokens: int) -> str:
        """Truncate long text content to fit within token limit."""
        if self.token_counter.count_tokens(text) <= max_tokens:
            return text

        estimated_chars = max(50, int(max_tokens * 2.5))
        truncated = text[:estimated_chars]
        while self.token_counter.count_tokens(truncated) > max_tokens and len(truncated) > 20:
            truncated = truncated[: int(len(truncated) * 0.8)]
        return truncated


__all__ = [
    "DynamicSlicerEngine",
    "HeuristicTokenCounter",
    "ITokenCounter",
    "SlicedContextResult",
    "SlicedKnowledgeResult",
    "SlicerWeights",
    "calculate_match_score",
    "calculate_recency_score",
    "compute_document_score",
    "format_knowledge_context_markdown",
    "format_knowledge_context_xml",
    "tokenize_text",
]
