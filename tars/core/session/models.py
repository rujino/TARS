"""Data models and enums for session lifecycle, time decay, and routing decisions."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SessionRoutingAction(str, Enum):
    """Actions performed during smart session routing."""

    MAINTAIN = "MAINTAIN"
    BRANCH_BRIDGE = "BRANCH_BRIDGE"
    FRESH_RESET = "FRESH_RESET"
    TOPIC_SHIFT = "TOPIC_SHIFT"
    NATURAL_RESET = "NATURAL_RESET"


class TopicShiftResult(BaseModel):
    """Result of semantic topic shift evaluation."""

    model_config = ConfigDict(extra="ignore")

    is_topic_shift: bool = Field(default=False, description="True if a topic shift is detected")
    new_topic: str | None = Field(
        default=None, description="Inferred new topic title or description"
    )
    confidence: float = Field(default=1.0, description="Confidence score of topic shift detection")


class SessionRoutingDecision(BaseModel):
    """Output summary of a session routing evaluation."""

    model_config = ConfigDict(extra="ignore")

    action: SessionRoutingAction = Field(..., description="Action taken by session manager")
    session_id: str = Field(..., description="Active session ID after routing")
    is_reset: bool = Field(
        default=False, description="True if this routing action was triggered by a reset command"
    )
    bridge_summary: str | None = Field(
        default=None, description="Bridge summary text if branched via time decay"
    )
    reason: str = Field(default="", description="Human-readable explanation of the routing action")


# Alias for backward/spec compatibility in orchestrator state
RoutingDecision = SessionRoutingDecision

__all__ = [
    "RoutingDecision",
    "SessionRoutingAction",
    "SessionRoutingDecision",
    "TopicShiftResult",
]

