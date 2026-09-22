"""Data schemas for proactive utterance threshold scoring."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tars.domains.proactive.scanner.schemas import UtteranceCandidate


class ThresholdScore(BaseModel):
    """Component-level breakdown of the proactive threshold score."""

    model_config = ConfigDict(extra="ignore")

    time_score: float = Field(..., ge=0.0, le=10.0, description="Score based on elapsed decay")
    importance_score: float = Field(..., ge=0.0, le=10.0, description="Base importance score")
    context_score: float = Field(..., ge=0.0, le=10.0, description="Contextual bonus score")
    urgency_bonus: float = Field(default=0.0, description="Deadline urgency increment")
    fatigue_penalty: float = Field(default=0.0, description="Deducted penalty from recent sends")
    raw_composite: float = Field(..., description="Pre-penalty combined score")
    final_score: float = Field(..., ge=0.0, le=10.0, description="Final clamped score (0.0 to 10.0)")


class ThresholdVerdict(BaseModel):
    """Final decision from UtteranceThresholdScorer."""

    model_config = ConfigDict(extra="ignore")

    candidate: UtteranceCandidate
    final_score: float
    is_above_threshold: bool
    score_breakdown: ThresholdScore
    suppressed_reason: str | None = None  # None | "daily_limit" | "silence_cooldown" | "low_score"


__all__ = [
    "ThresholdScore",
    "ThresholdVerdict",
]
