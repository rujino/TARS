"""TARS Knowledge Curator Package."""

from tars.domains.knowledge.curator.agent import KnowledgeCuratorAgent
from tars.domains.knowledge.curator.schemas import (
    AutoAcceptReviewHandler,
    CurationProposal,
    ICurationReviewHandler,
    InteractiveUserReviewHandler,
)
from tars.domains.knowledge.curator.prompts import CURATOR_SYSTEM_PROMPT

__all__ = [
    "AutoAcceptReviewHandler",
    "CURATOR_SYSTEM_PROMPT",
    "CurationProposal",
    "ICurationReviewHandler",
    "InteractiveUserReviewHandler",
    "KnowledgeCuratorAgent",
]
