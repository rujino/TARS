"""TARS Dynamic Slicer Engine for multi-factor ranking, relation expansion, and token budget packing."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import BaseMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.okf.models import OKFDocument, OKFMetadata
from tars.slicer.models import (
    CHAT_TYPE_MAP,
    GREETING_TYPE_MAP,
    IMPORTANCE_SCORE_MAP,
    PROFILE_TYPE_MAPS,
    PROFILE_WEIGHTS,
    TASK_TYPE_MAP,
    TYPE_SCORE_MAP,
    HeuristicTokenCounter,
    ITokenCounter,
    SlicedContextResult,
    SlicedKnowledgeResult,
    SlicerProfile,
    SlicerWeights,
)

logger = logging.getLogger("tars.slicer")

TOKEN_SPLIT_REGEX = re.compile(r"[\s,._\-\[\]\(\)\{\}\"\'/\\;:]+")


def tokenize_text(text: str) -> set[str]:
    """Tokenize and normalize text into unique lowercase tokens."""
    if not text:
        return set()
    raw_tokens = TOKEN_SPLIT_REGEX.split(text.lower())
    return {t.strip() for t in raw_tokens if len(t.strip()) > 0}


def extract_context_tokens(
    context_messages: Sequence[str | BaseMessage | dict[str, Any]] | None,
    max_turns: int = 5,
) -> set[str]:
    """Extract normalized tokens from recent conversation context turns."""
    if not context_messages:
        return set()

    recent_turns = context_messages[-max_turns:]
    collected_tokens: set[str] = set()

    for turn in recent_turns:
        if isinstance(turn, str):
            collected_tokens.update(tokenize_text(turn))
        elif isinstance(turn, BaseMessage):
            content = str(getattr(turn, "content", ""))
            collected_tokens.update(tokenize_text(content))
        elif isinstance(turn, dict):
            content = str(turn.get("content", turn.get("text", "")))
            collected_tokens.update(tokenize_text(content))

    return collected_tokens


def calculate_match_score(
    metadata: OKFMetadata,
    query_tokens: set[str],
    active_tags: set[str],
    context_tokens: set[str] | None = None,
    content: str | None = None,
) -> float:
    """Calculate query keyword, multi-turn context, and tag matching score in range [0.0, 1.0]."""
    if not query_tokens and not active_tags and not context_tokens:
        return 0.0

    doc_tags = {tag.lower().strip() for tag in metadata.tags if tag.strip()}

    # 1. Active tags overlap (high confidence explicit filter)
    tag_score = 0.0
    if active_tags:
        overlap = len(active_tags.intersection(doc_tags))
        tag_score = overlap / max(1, len(active_tags))

    # 2. Query tokens vs doc tags
    q_tag_score = 0.0
    if query_tokens and doc_tags:
        overlap = len(query_tokens.intersection(doc_tags))
        q_tag_score = overlap / max(1, len(doc_tags))

    # Context tokens vs doc tags
    if context_tokens and doc_tags:
        ctx_overlap = len(context_tokens.intersection(doc_tags))
        ctx_tag_score = ctx_overlap / max(1, len(doc_tags))
        q_tag_score = max(q_tag_score, (q_tag_score * 0.7) + (ctx_tag_score * 0.3))

    # 3. Query tokens vs title, category, id
    q_text_score = 0.0
    title_category_str = f"{metadata.title} {metadata.category or ''} {metadata.id}".lower()
    title_tokens = tokenize_text(title_category_str)
    if query_tokens and title_tokens:
        overlap = len(query_tokens.intersection(title_tokens))
        q_text_score = overlap / max(1, len(title_tokens))

    # Multi-turn context tokens vs title/category
    if context_tokens and title_tokens:
        ctx_overlap = len(context_tokens.intersection(title_tokens))
        ctx_text_score = ctx_overlap / max(1, len(title_tokens))
        q_text_score = max(q_text_score, (q_text_score * 0.7) + (ctx_text_score * 0.3))

    # 4. Content keyword & substring matching if content is available
    c_score = 0.0
    if content:
        content_lower = content.lower()
        if query_tokens:
            content_tokens = tokenize_text(content_lower)
            c_overlap = len(query_tokens.intersection(content_tokens))
            c_score = min(1.0, c_overlap / max(1, min(10, len(content_tokens))))

        # Substring bonus for full phrase queries
        query_raw = " ".join(sorted(query_tokens))
        if query_raw and (query_raw in content_lower or query_raw in title_category_str):
            c_score = min(1.0, c_score + 0.20)

    # 5. Combined similarity score (S_sim)
    if content:
        combined = (
            (0.35 * tag_score) + (0.30 * q_tag_score) + (0.20 * q_text_score) + (0.15 * c_score)
        )
    else:
        combined = (0.45 * tag_score) + (0.35 * q_tag_score) + (0.20 * q_text_score)

    return min(1.0, max(0.0, combined))


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
    profile: SlicerProfile | str = SlicerProfile.CHAT,
    context_tokens: set[str] | None = None,
    content: str | None = None,
) -> float:
    """Compute combined 5-factor score for a single OKF document."""
    # 1. S_imp: Importance score
    imp_score = IMPORTANCE_SCORE_MAP.get(metadata.importance, 0.50)

    # 2. S_sim: Context & Keyword matching score
    match_score = calculate_match_score(
        metadata=metadata,
        query_tokens=query_tokens,
        active_tags=active_tags,
        context_tokens=context_tokens,
        content=content,
    )

    # 3. S_type: Profile-aware type score
    try:
        resolved_profile = (
            profile if isinstance(profile, SlicerProfile) else SlicerProfile(str(profile).lower())
        )
    except ValueError:
        resolved_profile = SlicerProfile.CHAT

    type_map = PROFILE_TYPE_MAPS.get(resolved_profile, TYPE_SCORE_MAP)
    type_score = type_map.get(metadata.type, 0.50)

    # 4. S_rec: Recency score
    rec_score = calculate_recency_score(metadata.updated_at)

    # Combine weighted factors
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
        self._custom_weights: SlicerWeights | None = weights
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
        context_messages: Sequence[str | BaseMessage] | None = None,
        active_tags: list[str] | None = None,
        token_budget: int = 1500,
        profile: SlicerProfile | str = SlicerProfile.CHAT,
    ) -> SlicedContextResult:
        """Slice a provided collection of OKF documents within token budget."""
        if not docs:
            return SlicedContextResult(
                selected_documents=[],
                total_estimated_tokens=0,
                formatted_context="",
                scores={},
            )

        try:
            resolved_profile = (
                profile
                if isinstance(profile, SlicerProfile)
                else SlicerProfile(str(profile).lower())
            )
        except ValueError:
            resolved_profile = SlicerProfile.CHAT

        # Resolve weights: use explicit custom weights if provided, else profile weights
        effective_weights = (
            self._custom_weights
            if self._custom_weights is not None
            else PROFILE_WEIGHTS.get(resolved_profile, self.weights)
        )

        query_tokens = tokenize_text(query)
        context_tokens = extract_context_tokens(context_messages)
        norm_active_tags = {t.lower().strip() for t in (active_tags or []) if t.strip()}

        # 1. Base multi-factor scoring (5-Factor)
        doc_map: dict[str, OKFDocument] = {doc.metadata.id: doc for doc in docs}
        score_map: dict[str, float] = {}

        for okf_id, doc in doc_map.items():
            score = compute_document_score(
                metadata=doc.metadata,
                query_tokens=query_tokens,
                active_tags=norm_active_tags,
                weights=effective_weights,
                profile=resolved_profile,
                context_tokens=context_tokens,
                content=doc.content,
            )
            score_map[okf_id] = score

        # 2. Relation expansion & graph boosting with cycle prevention
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
        context_messages: Sequence[str | BaseMessage] | None = None,
        active_tags: list[str] | None = None,
        token_budget: int = 1500,
        profile: SlicerProfile | str = SlicerProfile.CHAT,
        db_session: AsyncSession | None = None,
    ) -> list[OKFDocument]:
        """Slice and return most relevant OKF documents for a user from storage or DB index.

        Conforms to PROJECT.md interface contract.
        """
        session_to_use = db_session if db_session is not None else self._db_session
        all_docs: list[OKFDocument] = []

        query_tokens = tokenize_text(query)
        norm_active_tags = {t.lower().strip() for t in (active_tags or []) if t.strip()}

        if session_to_use is not None and self.storage_manager is not None:
            all_docs = await self._fetch_via_db(
                user_id=user_id,
                db_session=session_to_use,
                query_tokens=query_tokens,
                active_tags=norm_active_tags,
            )

        if not all_docs and self.storage_manager is not None:
            try:
                all_docs = await self.storage_manager.list_okf_files(user_id)
            except Exception as e:
                logger.warning("Failed to list files from storage for user %s: %s", user_id, e)
                all_docs = []

        result = await self.slice_documents(
            docs=all_docs,
            query=query,
            context_messages=context_messages,
            active_tags=active_tags,
            token_budget=token_budget,
            profile=profile,
        )
        return result.selected_documents

    async def slice_knowledge(
        self,
        user_id: str,
        query: str = "",
        context_messages: Sequence[str | BaseMessage] | None = None,
        token_budget: int = 1500,
        profile: str = "chat",
        db: AsyncSession | None = None,
    ) -> SlicedKnowledgeResult:
        """Alias method matching PROJECT.md interface contract returning SlicedKnowledgeResult."""
        session_to_use = db if db is not None else self._db_session
        all_docs: list[OKFDocument] = []

        query_tokens = tokenize_text(query)

        if session_to_use is not None and self.storage_manager is not None:
            all_docs = await self._fetch_via_db(
                user_id=user_id,
                db_session=session_to_use,
                query_tokens=query_tokens,
            )

        if not all_docs and self.storage_manager is not None:
            try:
                all_docs = await self.storage_manager.list_okf_files(user_id)
            except Exception as e:
                logger.warning("Failed to list files from storage for user %s: %s", user_id, e)
                all_docs = []

        return await self.slice_documents(
            docs=all_docs,
            query=query,
            context_messages=context_messages,
            token_budget=token_budget,
            profile=profile,
        )

    def _expand_relations(
        self,
        doc_map: dict[str, OKFDocument],
        score_map: dict[str, float],
    ) -> dict[str, float]:
        """Expand depends_on and related_to relations with cycle detection."""
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

            # 1. depends_on: Essential dependency promotion (95% seed score)
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
        query_tokens: set[str] | None = None,
        active_tags: set[str] | None = None,
        candidate_limit: int = 25,
    ) -> list[OKFDocument]:
        """Pre-query DB metadata index for fast candidate pre-filtering before disk I/O."""
        try:
            from tars.db.models import UserWikiIndex

            stmt = select(UserWikiIndex).where(UserWikiIndex.user_id == user_id)
            result = await db_session.execute(stmt)
            records = result.scalars().all()

            if not records:
                return []

            # If user has fewer records than limit, read all of them
            if len(records) <= candidate_limit:
                candidate_ids = [r.okf_id for r in records]
            else:
                # Fast in-memory metadata scoring on DB index records
                scored_candidates: list[tuple[str, float]] = []
                for rec in records:
                    rec_tags = set(rec.tags) if isinstance(rec.tags, list) else set()
                    tag_overlap = len(rec_tags.intersection(active_tags)) if active_tags else 0
                    q_overlap = len(rec_tags.intersection(query_tokens)) if query_tokens else 0
                    title_tokens = tokenize_text(f"{rec.title} {rec.category or ''}")
                    title_overlap = (
                        len(query_tokens.intersection(title_tokens)) if query_tokens else 0
                    )
                    meta_score = (
                        (tag_overlap * 2.0)
                        + (q_overlap * 1.5)
                        + (title_overlap * 1.0)
                        + (1.0 if rec.importance == "critical" else 0.5)
                    )
                    scored_candidates.append((rec.okf_id, meta_score))

                scored_candidates.sort(key=lambda x: x[1], reverse=True)
                candidate_ids = [c[0] for c in scored_candidates[:candidate_limit]]

            docs: list[OKFDocument] = []
            for okf_id in candidate_ids:
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
    "CHAT_TYPE_MAP",
    "DynamicSlicerEngine",
    "GREETING_TYPE_MAP",
    "HeuristicTokenCounter",
    "IMPORTANCE_SCORE_MAP",
    "ITokenCounter",
    "PROFILE_TYPE_MAPS",
    "PROFILE_WEIGHTS",
    "SlicedContextResult",
    "SlicedKnowledgeResult",
    "SlicerProfile",
    "SlicerWeights",
    "TASK_TYPE_MAP",
    "TYPE_SCORE_MAP",
    "calculate_match_score",
    "calculate_recency_score",
    "compute_document_score",
    "extract_context_tokens",
    "format_knowledge_context_markdown",
    "format_knowledge_context_xml",
    "tokenize_text",
]
