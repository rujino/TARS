"""Proactive utterance scoring policies and review cycle abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from tars.domains.knowledge.spec.schemas import OKFImportance, OKFType


class ReviewCyclePolicy(ABC):
    """Abstract interface for determining optimal review intervals (in days).

    Enables dynamic substitution: Global default -> User customized -> Adaptive ML.
    """

    @abstractmethod
    def days_for(self, okf_type: OKFType, importance: OKFImportance) -> int:
        """Calculate recommended review cycle interval in days."""
        ...


@dataclass(frozen=True)
class DefaultReviewCyclePolicy(ReviewCyclePolicy):
    """Default global review cycle policy based on Ebbinghaus forgetting curve.

    Modification guidelines:
        - Immediate tweaks: Adjust the dataclass default attributes below.
        - Per-user overrides: Implement a DB-backed subclass of ReviewCyclePolicy.
        - Future ML adaptations: Swap with an adaptive spacing policy.
    """

    # OKFType.CONCEPT: Theoretical conceptual understanding
    concept_low_days: int = 14
    concept_medium_days: int = 7
    concept_high_days: int = 3
    concept_critical_days: int = 1

    # OKFType.PROCEDURE: Operational / step-by-step procedures
    procedure_low_days: int = 21
    procedure_medium_days: int = 10
    procedure_high_days: int = 5
    procedure_critical_days: int = 2

    # OKFType.RULE: Policies and constraints (lower decay rate)
    rule_low_days: int = 30
    rule_medium_days: int = 14
    rule_high_days: int = 7
    rule_critical_days: int = 3

    # Fallback for references, preferences, entities
    fallback_days: int = 14

    def days_for(self, okf_type: OKFType, importance: OKFImportance) -> int:
        attr_key = f"{okf_type.value}_{importance.value}_days"
        return int(getattr(self, attr_key, self.fallback_days))


@dataclass(frozen=True)
class ProactiveScorerPolicy:
    """Mathematical constants and threshold configurations for utterance decisions.

    Zero-regex, deterministic math constraints.
    """

    # Minimum composite score required to promote candidate to an utterance
    utterance_threshold: float = 6.0

    # Linear weights for score components (must sum to 1.0)
    weight_time: float = 0.40
    weight_importance: float = 0.35
    weight_context: float = 0.25

    # Base importance points (0.0 to 10.0 scale)
    importance_scores: dict[str, float] = field(
        default_factory=lambda: {
            "low": 2.0,
            "medium": 5.0,
            "high": 8.0,
            "critical": 10.0,
        }
    )

    # Fatigue penalty control
    fatigue_penalty_per_send: float = 2.0  # Points deducted per send in fatigue window
    fatigue_window_hours: int = 24         # Lookback window in hours
    max_daily_proactive: int = 3           # Hard daily ceiling per user
    min_silence_hours: int = 2             # Minimum quiet cooldown between utterances

    # Context continuity bonus (if discussed in recent dialogue)
    context_bonus: float = 3.0

    # Deadline urgency bonus (applied if deadline is within window)
    deadline_urgency_within_hours: int = 24
    deadline_urgency_bonus: float = 2.0


__all__ = [
    "DefaultReviewCyclePolicy",
    "ProactiveScorerPolicy",
    "ReviewCyclePolicy",
]
