"""Deterministic proactive threshold scorer implementation.

Zero-Regex, Pure Python mathematical evaluation (0ms latency).
"""

from __future__ import annotations

from tars.domains.proactive.scanner.schemas import UtteranceCandidate
from tars.domains.proactive.scorer.policy import ProactiveScorerPolicy
from tars.domains.proactive.scorer.schemas import ThresholdScore, ThresholdVerdict


class UtteranceThresholdScorer:
    """Computes composite proactive desire scores and evaluates activation thresholds."""

    def __init__(self, policy: ProactiveScorerPolicy | None = None) -> None:
        self.policy = policy or ProactiveScorerPolicy()

    def evaluate(
        self,
        candidate: UtteranceCandidate,
        recent_send_count: int = 0,
        hours_since_last_send: float | None = None,
        hours_until_deadline: float | None = None,
    ) -> ThresholdVerdict:
        """Calculate proactive utterance score and render a threshold verdict.

        Zero-Regex standard: Performs purely numeric arithmetic and boolean checks.
        """
        # 1. Time decay score
        cycle = max(1, candidate.review_cycle_days)
        time_score = min(10.0, (candidate.elapsed_days / cycle) * 10.0)

        # 2. Importance score
        importance_key = candidate.importance.value
        importance_score = self.policy.importance_scores.get(importance_key, 5.0)

        # 3. Context continuity score
        context_score = (
            self.policy.context_bonus if candidate.has_conversation_context else 0.0
        )

        # 4. Deadline urgency bonus
        urgency_bonus = 0.0
        if (
            hours_until_deadline is not None
            and 0.0 <= hours_until_deadline <= self.policy.deadline_urgency_within_hours
        ):
            urgency_bonus = self.policy.deadline_urgency_bonus

        # 5. Composite raw score
        raw_composite = (
            (self.policy.weight_time * time_score)
            + (self.policy.weight_importance * importance_score)
            + (self.policy.weight_context * context_score)
            + urgency_bonus
        )

        # 6. Fatigue penalty deduction
        fatigue_penalty = recent_send_count * self.policy.fatigue_penalty_per_send
        final_score = round(max(0.0, min(10.0, raw_composite - fatigue_penalty)), 2)

        breakdown = ThresholdScore(
            time_score=round(time_score, 2),
            importance_score=round(importance_score, 2),
            context_score=round(context_score, 2),
            urgency_bonus=round(urgency_bonus, 2),
            fatigue_penalty=round(fatigue_penalty, 2),
            raw_composite=round(raw_composite, 2),
            final_score=final_score,
        )

        # 7. Suppression guardrail checks
        if recent_send_count >= self.policy.max_daily_proactive:
            return ThresholdVerdict(
                candidate=candidate,
                final_score=final_score,
                is_above_threshold=False,
                score_breakdown=breakdown,
                suppressed_reason="daily_limit",
            )

        if (
            hours_since_last_send is not None
            and hours_since_last_send < self.policy.min_silence_hours
        ):
            return ThresholdVerdict(
                candidate=candidate,
                final_score=final_score,
                is_above_threshold=False,
                score_breakdown=breakdown,
                suppressed_reason="silence_cooldown",
            )

        if final_score < self.policy.utterance_threshold:
            return ThresholdVerdict(
                candidate=candidate,
                final_score=final_score,
                is_above_threshold=False,
                score_breakdown=breakdown,
                suppressed_reason="low_score",
            )

        return ThresholdVerdict(
            candidate=candidate,
            final_score=final_score,
            is_above_threshold=True,
            score_breakdown=breakdown,
            suppressed_reason=None,
        )


__all__ = ["UtteranceThresholdScorer"]
