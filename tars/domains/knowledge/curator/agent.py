"""TARS Knowledge Curator Agent Implementation.

Autonomous agent managing the 2-Tier Knowledge Architecture:
- Micro Fact extraction and slot profile persistence.
- Macro OKF 2.0 document curation, cross-linking with [[wiki-links]], and vault filing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from tars.domains.knowledge.curator.prompts import CURATOR_SYSTEM_PROMPT
from tars.domains.knowledge.curator.schemas import (
    AutoAcceptReviewHandler,
    CurationProposal,
    ICurationReviewHandler,
)
from tars.domains.knowledge.micro.manager import MicroFactManager
from tars.domains.knowledge.micro.schemas import MicroFact
from tars.domains.knowledge.spec.schemas import (
    OKFDocument,
    OKFImportance,
    OKFMetadata,
    OKFSource,
    OKFStatus,
    OKFType,
)
from tars.domains.knowledge.spec.wikilink import extract_target_ids
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.engine.adapters.base import BaseLLMAdapter

logger = logging.getLogger("tars.domains.knowledge.curator.agent")


class KnowledgeCuratorAgent:
    """Autonomous curator agent that analyzes, structures, cross-links, and persists user knowledge."""

    def __init__(
        self,
        llm_adapter: BaseLLMAdapter | Any,
        storage_manager: FileStorageManager | None = None,
        micro_fact_manager: MicroFactManager | None = None,
        review_handler: ICurationReviewHandler | None = None,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.storage_manager = storage_manager or FileStorageManager()
        self.micro_fact_manager = micro_fact_manager or MicroFactManager(self.storage_manager)
        self.review_handler = review_handler or AutoAcceptReviewHandler()

    def _clean_json_response(self, raw_text: str) -> str:
        """Strip markdown code fences from LLM response."""
        text = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text

    async def curate(
        self,
        user_id: str,
        raw_text: str,
        source_hint: str = "manual",
    ) -> dict[str, Any]:
        """Execute the 5-step curation pipeline for raw input text.

        Returns:
            Dict containing curated OKFDocuments, saved MicroFacts, and proposals.
        """
        if not raw_text or not raw_text.strip():
            return {"micro_facts": [], "curated_docs": [], "proposals": []}

        # Step 1: Scan existing vault documents to prepare cross-linking context
        existing_docs = await self.storage_manager.list_okf_files(user_id)
        existing_summary_lines: list[str] = []
        for doc in existing_docs:
            alias_str = f" (aliases: {', '.join(doc.aliases)})" if doc.aliases else ""
            existing_summary_lines.append(f"- ID: {doc.id} | Title: {doc.title}{alias_str}")

        context_prompt = (
            "[EXISTING VAULT DOCUMENTS FOR CROSS-LINKING]\n"
            + ("\n".join(existing_summary_lines) if existing_summary_lines else "None yet.")
            + "\n\n[USER INPUT TO CURATE]\n"
            + raw_text.strip()
        )

        messages = [
            SystemMessage(content=CURATOR_SYSTEM_PROMPT),
            HumanMessage(content=context_prompt),
        ]

        # Step 2: Invoke LLM
        response = await self.llm_adapter.agenerate(messages, temperature=0.1)
        raw_content = str(getattr(response, "content", response))
        cleaned_json = self._clean_json_response(raw_content)

        try:
            payload = json.loads(cleaned_json)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse Curator LLM response as JSON: %s\nRaw: %s", exc, cleaned_json
            )
            return {"micro_facts": [], "curated_docs": [], "proposals": []}

        # Step 3: Process Tier 1 Micro Facts
        saved_facts: list[MicroFact] = []
        raw_facts = payload.get("micro_facts", [])
        if isinstance(raw_facts, list):
            for fact_item in raw_facts:
                if isinstance(fact_item, dict) and "key" in fact_item and "value" in fact_item:
                    k = str(fact_item["key"]).strip()
                    v = str(fact_item["value"]).strip()
                    cat = str(fact_item.get("category", "preference")).strip()
                    if k and v:
                        fact = await self.micro_fact_manager.set_fact(
                            user_id=user_id,
                            key=k,
                            value=v,
                            category=cat,
                        )
                        saved_facts.append(fact)

        # Step 4 & 5: Process Tier 2 Macro Documents & Review Proposals
        curated_docs: list[OKFDocument] = []
        proposals: list[CurationProposal] = []
        raw_docs = payload.get("documents", [])

        if isinstance(raw_docs, list):
            for doc_data in raw_docs:
                if not isinstance(doc_data, dict):
                    continue

                doc_id = str(doc_data.get("doc_id", "")).strip()
                title = str(doc_data.get("title", "")).strip()
                content = str(doc_data.get("content", "")).strip()

                if not doc_id or not title:
                    continue

                doc_type_str = str(doc_data.get("type", "concept")).lower()
                doc_type = OKFType.CONCEPT
                if doc_type_str in OKFType._value2member_map_:
                    doc_type = OKFType(doc_type_str)

                importance_str = str(doc_data.get("importance", "medium")).lower()
                importance = OKFImportance.MEDIUM
                if importance_str in OKFImportance._value2member_map_:
                    importance = OKFImportance(importance_str)

                is_update = bool(doc_data.get("is_update", False))
                diff_summary = doc_data.get("diff_summary")

                created_links = extract_target_ids(content)

                frontmatter_dict: dict[str, Any] = {
                    "okf_version": "2.0",
                    "id": doc_id,
                    "type": doc_type,
                    "title": title,
                    "category": doc_data.get("category"),
                    "tags": doc_data.get("tags", []),
                    "aliases": doc_data.get("aliases", []),
                    "importance": importance,
                    "status": OKFStatus.VERIFIED,
                    "source": OKFSource.AUTO_EXTRACTED
                    if source_hint == "auto"
                    else OKFSource.MANUAL,
                }

                proposal = CurationProposal(
                    action="update" if is_update else "create",
                    target_doc_id=doc_id,
                    frontmatter=frontmatter_dict,
                    content=content,
                    created_links=created_links,
                    diff_summary=diff_summary,
                )
                proposals.append(proposal)

                # Submit to Review Handler (AutoAccept or Human-in-the-Loop)
                approved = await self.review_handler.handle_proposal(proposal)
                if approved:
                    metadata = OKFMetadata(**frontmatter_dict)
                    doc = OKFDocument(metadata=metadata, content=content)
                    await self.storage_manager.save_okf_file(user_id=user_id, doc=doc)
                    curated_docs.append(doc)
                    logger.info(
                        "KnowledgeCurator persisted OKF 2.0 document '%s' for user '%s'",
                        doc_id,
                        user_id,
                    )
                else:
                    logger.info(
                        "KnowledgeCurator proposal for '%s' rejected by review handler", doc_id
                    )

        return {
            "micro_facts": saved_facts,
            "curated_docs": curated_docs,
            "proposals": proposals,
        }


__all__ = ["KnowledgeCuratorAgent"]
