"""TARS Self-Evolving Knowledge Extractor Package."""

from tars.extractor.prompts import KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
from tars.extractor.worker import (
    KnowledgeExtractionResult,
    SelfEvolvingKnowledgeWorker,
)

__all__ = [
    "KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT",
    "KnowledgeExtractionResult",
    "SelfEvolvingKnowledgeWorker",
]
