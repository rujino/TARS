"""TARS Self-Evolving Knowledge Extractor Package."""

from tars.domains.knowledge.extractor.prompts import KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
from tars.domains.knowledge.extractor.worker import (
    KnowledgeExtractionResult,
    SelfEvolvingKnowledgeWorker,
)

__all__ = [
    "KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT",
    "KnowledgeExtractionResult",
    "SelfEvolvingKnowledgeWorker",
]
