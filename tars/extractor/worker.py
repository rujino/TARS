"""Self-Evolving Knowledge Extractor Worker & Auto-Extracted OKF Synchronizer.

Provides:
- KnowledgeExtractionResult Pydantic model.
- SelfEvolvingKnowledgeWorker for background fact extraction, OKF document persistence,
  and atomic DB metadata synchronization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
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
from tars.db.models import UserWikiIndex
from tars.extractor.prompts import KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
from tars.storage.manager import FileStorageManager
from tars.storage.reconciliation import StorageDBReconciliationEngine

logger = logging.getLogger("tars.extractor.worker")

CASUAL_CHAT_SKIP_REGEX = re.compile(
    r"^(안녕|하이|반가워|hello|hi|hey|test|ping|pong|bye|goodbye|잘가|고마워|thanks|thank you|2\s*\+\s*2|\d+\s*[\+\-\*\/]\s*\d+)$",
    re.IGNORECASE,
)


def _default_relations() -> dict[str, list[str]]:
    return {"depends_on": [], "related_to": []}


class KnowledgeExtractionResult(BaseModel):
    """Structured extraction payload produced by the extractor LLM."""

    model_config = ConfigDict(extra="ignore")

    should_extract: bool = Field(
        default=False, description="True if valuable knowledge was identified"
    )
    is_conflict_or_update: bool = Field(
        default=False, description="True if this updates/contradicts an existing wiki"
    )
    target_existing_id: str | None = Field(
        default=None, description="Existing OKF ID to overwrite if updating"
    )
    doc_id: str | None = Field(
        default=None, description="Suggested unique slug ID for the OKF document"
    )
    type: str = Field(
        default="concept",
        description="OKF document type (rule, preference, fact, concept, procedure)",
    )
    title: str = Field(default="", description="Human-readable title")
    category: str | None = Field(default=None, description="Category partition")
    tags: list[str] = Field(default_factory=list, description="Descriptive search tags")
    importance: str = Field(
        default="medium", description="Importance level (low, medium, high, critical)"
    )
    content: str = Field(default="", description="Markdown body content")
    relations: dict[str, list[str]] = Field(
        default_factory=_default_relations,
        description="Graph relation links",
    )


class SelfEvolvingKnowledgeWorker:
    """Background worker analyzing conversation turns and maintaining the user's OKF knowledge base."""

    def __init__(
        self,
        extractor_llm: BaseLLMAdapter | Any,
        storage_manager: FileStorageManager,
    ) -> None:
        self.extractor_llm = extractor_llm
        self.storage_manager = storage_manager
        self.reconciliation_engine = StorageDBReconciliationEngine(storage_manager=storage_manager)

    def _clean_json_response(self, raw_text: str) -> str:
        """Strip markdown code fences and extraneous text from LLM JSON response."""
        text = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    def _normalize_conversation_turns(
        self,
        conversation_turns: Sequence[BaseMessage | dict[str, Any] | str],
    ) -> list[BaseMessage]:
        """Convert input sequence into standard BaseMessage objects."""
        messages: list[BaseMessage] = []
        for turn in conversation_turns:
            if isinstance(turn, BaseMessage):
                messages.append(turn)
            elif isinstance(turn, dict):
                role = str(turn.get("role", turn.get("type", "human"))).lower()
                content = str(turn.get("content", turn.get("text", "")))
                if role in ("human", "user"):
                    messages.append(HumanMessage(content=content))
                elif role in ("ai", "assistant", "bot"):
                    messages.append(AIMessage(content=content))
                elif role in ("system",):
                    messages.append(SystemMessage(content=content))
                else:
                    messages.append(HumanMessage(content=content))
            elif isinstance(turn, str):
                messages.append(HumanMessage(content=turn))
        return messages

    async def _fetch_existing_knowledge_summary(
        self,
        user_id: str,
        db_session: AsyncSession | None,
    ) -> list[dict[str, str]]:
        """Fetch concise summary of user's existing knowledge documents."""
        summaries: list[dict[str, str]] = []
        if db_session is not None:
            try:
                stmt = select(
                    UserWikiIndex.okf_id,
                    UserWikiIndex.title,
                    UserWikiIndex.type,
                    UserWikiIndex.category,
                ).where(UserWikiIndex.user_id == user_id)
                res = await db_session.execute(stmt)
                for row in res.all():
                    summaries.append(
                        {
                            "id": str(row[0]),
                            "title": str(row[1]),
                            "type": str(row[2]),
                            "category": str(row[3] or "general"),
                        }
                    )
                return summaries
            except Exception as err:
                logger.warning("Failed to fetch knowledge summary from DB: %s", err)

        # Fallback to storage
        try:
            files = await self.storage_manager.list_okf_files(user_id)
            for f in files:
                summaries.append(
                    {
                        "id": f.metadata.id,
                        "title": f.metadata.title,
                        "type": f.metadata.type.value,
                        "category": f.metadata.category or "general",
                    }
                )
        except Exception as ex:
            logger.warning("Failed to list knowledge from storage: %s", ex)

        return summaries

    async def extract_and_sync(
        self,
        user_id: str,
        conversation_turns: Sequence[BaseMessage | dict[str, Any] | str],
        db_session: AsyncSession | None = None,
    ) -> list[OKFDocument]:
        """Extract persistent knowledge from conversation turns and sync to storage and DB.

        Args:
            user_id: Unique user identifier.
            conversation_turns: Sequence of dialogue messages (HumanMessage, AIMessage, or dicts).
            db_session: Optional AsyncSession for updating UserWikiIndex metadata.

        Returns:
            List of newly extracted or updated OKFDocument instances (empty if none extracted).
        """
        if not user_id or not conversation_turns:
            return []

        norm_messages = self._normalize_conversation_turns(conversation_turns)
        if not norm_messages:
            return []

        # 1. Fast heuristic filter for transient/casual messages
        human_turns = [m for m in norm_messages if isinstance(m, HumanMessage)]
        if human_turns and len(human_turns) == 1:
            last_text = str(human_turns[-1].content).strip()
            if CASUAL_CHAT_SKIP_REGEX.match(last_text) or len(last_text) < 2:
                logger.debug("Skipping knowledge extraction for transient chatter: '%s'", last_text)
                return []

        # 2. Fetch existing knowledge to enable accurate conflict detection and updates
        existing_summaries = await self._fetch_existing_knowledge_summary(user_id, db_session)
        system_prompt = KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
        if existing_summaries:
            summary_json = json.dumps(existing_summaries, ensure_ascii=False, indent=2)
            system_prompt += f"\n\n[EXISTING USER KNOWLEDGE SUMMARY]\n{summary_json}"

        # 3. Invoke LLM for structured knowledge extraction with safety timeout
        try:
            llm_response = await asyncio.wait_for(
                self.extractor_llm.agenerate(
                    messages=norm_messages,
                    system_prompt=system_prompt,
                ),
                timeout=5.0,
            )
            raw_text = str(llm_response)
            cleaned_json = self._clean_json_response(raw_text)
            data = json.loads(cleaned_json)
            result = KnowledgeExtractionResult.model_validate(data)
        except Exception as err:
            logger.error("Extractor LLM response could not be parsed: %s", err, exc_info=True)
            return []

        if not result.should_extract or not result.content:
            logger.debug("Extractor determined no knowledge to persist for user %s", user_id)
            return []

        # 4. Determine effective document ID
        effective_id = result.target_existing_id or result.doc_id
        if not effective_id:
            effective_id = f"auto_fact_{int(datetime.now(UTC).timestamp())}"

        # 5. Resolve type and importance enums safely
        try:
            doc_type = OKFType(result.type.lower())
        except ValueError:
            doc_type = OKFType.CONCEPT

        try:
            doc_importance = OKFImportance(result.importance.lower())
        except ValueError:
            doc_importance = OKFImportance.MEDIUM

        now = datetime.now(UTC)
        title = result.title.strip() or effective_id.replace("_", " ").title()
        category = result.category or "general"
        tags = result.tags or [doc_type.value]

        depends_on = result.relations.get("depends_on", [])
        related_to = result.relations.get("related_to", [])

        meta = OKFMetadata(
            okf_version="1.0",
            id=effective_id,
            type=doc_type,
            title=title,
            category=category,
            tags=tags,
            importance=doc_importance,
            source=OKFSource.AUTO_EXTRACTED,
            relations=OKFRelations(depends_on=depends_on, related_to=related_to),
            created_at=now,
            updated_at=now,
        )

        doc = OKFDocument(metadata=meta, content=result.content.strip())

        # 6. Persist to file storage
        await self.storage_manager.save_okf_file(user_id=user_id, doc=doc)
        logger.info(
            "Persisted auto-extracted OKF document '%s' for user '%s'", effective_id, user_id
        )

        # 7. Atomic sync to DB metadata index via reconciliation engine
        if db_session is not None:
            try:
                doc_text = doc.to_markdown() if hasattr(doc, "to_markdown") else str(doc)
                file_hash = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()
                file_path = f"storage/users/{user_id}/wikis/{effective_id}.md"

                await self.reconciliation_engine.sync_single_document(
                    user_id=user_id,
                    doc=doc,
                    file_path=file_path,
                    file_hash=file_hash,
                    session=db_session,
                )
                await db_session.commit()
            except Exception as db_err:
                logger.error("Failed to sync OKF metadata to database: %s", db_err, exc_info=True)
                await db_session.rollback()

        return [doc]


__all__ = [
    "KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT",
    "KnowledgeExtractionResult",
    "SelfEvolvingKnowledgeWorker",
]
