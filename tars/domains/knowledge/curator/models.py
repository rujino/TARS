"""TARS Knowledge Curator Agent Data Models & Review Handler Interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CurationProposal(BaseModel):
    """Structured proposal produced by the Knowledge Curator Agent for a document."""

    model_config = ConfigDict(extra="ignore")

    action: Literal["create", "update", "split"] = Field(
        default="create", description="Action type: create, update, or split"
    )
    target_doc_id: str = Field(..., description="Document slug identifier")
    frontmatter: dict[str, Any] = Field(default_factory=dict, description="OKF 2.0 metadata fields")
    content: str = Field(default="", description="Markdown body containing [[wiki-links]]")
    created_links: list[str] = Field(default_factory=list, description="Target document IDs linked")
    diff_summary: str | None = Field(default=None, description="Summary of modifications if updating")


class ICurationReviewHandler(ABC):
    """Abstract interface for reviewing and approving curation proposals."""

    @abstractmethod
    async def handle_proposal(self, proposal: CurationProposal) -> bool:
        """Evaluate a proposal and return True if approved, False to reject."""
        pass


class AutoAcceptReviewHandler(ICurationReviewHandler):
    """Default autonomous handler: automatically approves all proposals."""

    async def handle_proposal(self, proposal: CurationProposal) -> bool:
        return True


class InteractiveUserReviewHandler(ICurationReviewHandler):
    """Interactive review handler stub for future Human-in-the-Loop workflows.

    Can be wired to WebSocket events, UI modals, or approval queues.
    """

    def __init__(self, callback: Any | None = None) -> None:
        self.callback = callback

    async def handle_proposal(self, proposal: CurationProposal) -> bool:
        if self.callback:
            res = self.callback(proposal)
            if hasattr(res, "__await__"):
                return bool(await res)
            return bool(res)
        # Default fallback to True if no callback configured
        return True


__all__ = [
    "AutoAcceptReviewHandler",
    "CurationProposal",
    "ICurationReviewHandler",
    "InteractiveUserReviewHandler",
]
