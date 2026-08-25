"""Self-Evolving Knowledge Extractor Worker & Auto-Extracted OKF Synchronizer.

Provides:
- KnowledgeExtractionResult Pydantic model.
- SelfEvolvingKnowledgeWorker for background fact extraction, OKF document persistence,
  and atomic DB metadata synchronization.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from langchain_core.messages import BaseMessage
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
from tars.storage.manager import FileStorageManager

logger = logging.getLogger("tars.extractor.worker")

KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT = """You are the TARS Knowledge Extraction Engine.
Analyze the following conversation turns between User and TARS.
Identify any persistent user facts, preferences, behavioral rules, or operational protocols worth remembering long-term.

Ignore transient chatter, greetings, math queries, temporary questions, or jokes.

Respond with ONLY a valid JSON object adhering to the following schema:
{
  "should_extract": true | false,
  "is_conflict_or_update": true | false,
  "target_existing_id": null | "<existing_okf_id>",
  "doc_id": "<slug_okf_id>",
  "type": "concept" | "rule" | "preference" | "fact" | "procedure",
  "title": "<Concise Title>",
  "category": "<category_name>",
  "tags": ["tag1", "tag2"],
  "importance": "low" | "medium" | "high" | "critical",
  "content": "<Markdown formatted knowledge content>",
  "relations": {
    "depends_on": [],
    "related_to": []
  }
}
If nothing valuable should be extracted, set "should_extract": false and content to empty string."""


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
        extractor_llm: BaseLLMAdapter,
        storage_manager: FileStorageManager,
    ) -> None:
        self.extractor_llm = extractor_llm
        self.storage_manager = storage_manager

    def _clean_json_response(self, raw_text: str) -> str:
        """Strip markdown code fences and extraneous text from LLM JSON response."""
        text = raw_text.strip()
        # Remove ```json ... ``` fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    async def extract_and_sync(
        self,
        user_id: str,
        conversation_turns: Sequence[BaseMessage],
        db_session: AsyncSession | None = None,
    ) -> list[OKFDocument]:
        """Extract persistent knowledge from conversation turns and sync to storage and DB.

        Args:
            user_id: Unique user identifier.
            conversation_turns: Sequence of recent dialogue messages (HumanMessage, AIMessage).
            db_session: Optional AsyncSession for updating UserWikiIndex metadata.

        Returns:
            List of newly extracted or updated OKFDocument instances (empty if none extracted).
        """
        if not user_id or not conversation_turns:
            return []

        try:
            llm_response = await self.extractor_llm.agenerate(
                messages=conversation_turns,
                system_prompt=KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT,
            )
            raw_text = str(llm_response)
            cleaned_json = self._clean_json_response(raw_text)
            data = json.loads(cleaned_json)
            result = KnowledgeExtractionResult.model_validate(data)
        except Exception as err:
            logger.error("Failed to parse extractor LLM response: %s", err, exc_info=True)
            return []

        if not result.should_extract or not result.content:
            logger.debug("Extractor determined no knowledge to persist for user %s", user_id)
            return []

        # Determine effective document ID
        effective_id = result.target_existing_id or result.doc_id
        if not effective_id:
            # Fallback doc_id generation
            effective_id = f"auto_fact_{int(datetime.now(UTC).timestamp())}"

        # Resolve type and importance enums safely
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

        # 1. Save to physical file storage
        await self.storage_manager.save_okf_file(user_id=user_id, doc=doc)
        logger.info(
            "Persisted auto-extracted OKF document '%s' for user '%s'", effective_id, user_id
        )

        # 2. Sync with database index if session provided
        if db_session is not None:
            try:
                stmt = select(UserWikiIndex).where(
                    UserWikiIndex.user_id == user_id,
                    UserWikiIndex.okf_id == effective_id,
                )
                res = await db_session.execute(stmt)
                existing_entry = res.scalar_one_or_none()

                file_path = f"storage/users/{user_id}/wikis/{effective_id}.md"
                tags_str = json.dumps(tags)

                if existing_entry is not None:
                    existing_entry.title = title
                    existing_entry.doc_type = doc_type.value
                    existing_entry.category = category
                    existing_entry.importance = doc_importance.value
                    existing_entry.tags = tags_str
                    existing_entry.file_path = file_path
                    existing_entry.updated_at = now
                else:
                    new_entry = UserWikiIndex(
                        user_id=user_id,
                        okf_id=effective_id,
                        file_path=file_path,
                        title=title,
                        doc_type=doc_type.value,
                        category=category,
                        importance=doc_importance.value,
                        tags=tags_str,
                        created_at=now,
                        updated_at=now,
                    )
                    db_session.add(new_entry)

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
