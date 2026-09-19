"""Floor Director Gatekeeper for Multi-Agent Companion Dialogue.

Provides deterministic 0ms code rules to evaluate turn routing across 4 conversation patterns:
1. SOLO: Single persona dominant or single-character session ($N=1$).
2. TAG_TEAM_REMEDIATION: Dual high desire under emotional crisis (System 1 emotional first-strike -> System 2 reality remedy).
3. DEBATE_BANTER: Dual high desire without crisis (collaborative discussion / banter).
4. GUARDRAIL_INTERVENTION: Low desire cutoff (all < 5) assigning minimal responder.

Includes direct mention priority (+4 bonus with word boundary/postposition matching).
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from tars.domains.persona.schemas import (
    PersonaDefinition,
    RoleType,
    RoutingPattern,
    SubconsciousStatePayload,
    TurnRoutingDecision,
)

logger = logging.getLogger("tars.engine.orchestrator.director")

# Regex pattern for emotional crisis keywords in Korean
CRISIS_KEYWORDS_REGEX = re.compile(
    r"(번아웃|자책|우울|힘들|지친|지쳐|포기|죽고\s*싶|괴로|취약|무너|멘붕|망했어|살기\s*싫)",
    re.IGNORECASE,
)

# Regex pattern for collective/all-persona mention keywords in Korean (e.g. '둘 다', '모두', '너희 둘 다', '다들')
COLLECTIVE_MENTION_REGEX = re.compile(
    r"(?:^|(?<![가-힣a-zA-Z0-9]))("
    r"둘\s*다|"
    r"둘\s*모두|"
    r"둘다|"
    r"너희\s*(?:들|둘\s*다|둘)?|"
    r"너네\s*(?:들|둘\s*다|둘)?|"
    r"모두(?:에게|한테|는|도)?|"
    r"다들|"
    r"다\s*같이|"
    r"함께|"
    r"전부|"
    r"두\s*(?:사람|녀석|명|분|마리)\s*(?:다|모두)?"
    r")(?:(?![가-힣a-zA-Z0-9])|$)",
    re.IGNORECASE,
)


class FloorDirectorGatekeeper:
    """Deterministic, 0ms latency code rules engine for multi-agent turn arbitration."""

    @classmethod
    def is_collective_mention(cls, user_text: str) -> bool:
        """Check if user text addresses all active personas collectively (e.g., '둘 다', '모두', '너희').

        Args:
            user_text: Raw user input text.

        Returns:
            True if user explicitly addresses all or dual personas together.
        """
        if not user_text:
            return False
        return bool(COLLECTIVE_MENTION_REGEX.search(user_text))

    @staticmethod
    def is_directly_mentioned(user_text: str, persona: PersonaDefinition) -> bool:
        """Check if user text directly mentions a persona name or ID with word/particle boundaries.

        Prevents false substring positives (e.g. '미우주적' vs '미우야').

        Args:
            user_text: Raw user input text.
            persona: PersonaDefinition to check for.

        Returns:
            True if persona is explicitly called or addressed.
        """
        if not user_text:
            return False

        # Korean postpositions / particles:
        # Longer compound particles first: 에게는, 한테도, 님께, 이랑, 으로, etc.
        korean_suffixes = (
            r"(?:"
            r"에게는|한테도|에게|한테|"
            r"님께|시여|씨|님|"
            r"이랑|랑|으로|로|과|와|"
            r"야|아|은|는|이|가|를|을|의|도"
            r")?"
        )
        boundary_start = r"(?<![가-힣a-zA-Z0-9])"
        boundary_end = r"(?![가-힣a-zA-Z0-9])"

        # Check persona name
        pattern_name = rf"{boundary_start}{re.escape(persona.name)}{korean_suffixes}{boundary_end}"
        if re.search(pattern_name, user_text, re.IGNORECASE):
            return True

        # Check persona id (e.g. 'vera', 'miu') with symmetric word boundary
        pattern_id = rf"{boundary_start}{re.escape(persona.id)}{korean_suffixes}{boundary_end}"
        if re.search(pattern_id, user_text, re.IGNORECASE):
            return True

        return False

    @classmethod
    def evaluate_turn_routing(
        cls,
        user_text: str,
        desire_scores: dict[str, int],
        active_personas: Sequence[PersonaDefinition],
        subconscious: SubconsciousStatePayload | None = None,
        recent_speakers: Sequence[str] | None = None,
    ) -> TurnRoutingDecision:
        """Arbitrate turn routing across active personas using deterministic 0ms code rules.

        Rules:
        - Rule 0 (Collective / Multi-Mention Guarantee): User mentions collective ('둘 다', '모두')
          or multiple personas -> Unconditionally guarantee multi-persona response (no solo cutoff).
        - Rule 1 (Direct Mention): User mentions persona name -> +4 bonus. Mentioned persona
          is never silenced into SOLO by an unmentioned persona.
        - Rule 2 (Tiki-taka / Dual High Desire): top1 >= 7 and top2 >= 7.
          - If emotional crisis: TAG_TEAM_REMEDIATION (System 1 first-strike -> System 2 remedy).
          - If normal/collaborative: DEBATE_BANTER.
        - Rule 3 (Solo Cutoff): Single persona, or top1 - top2 >= 3, or top2 < 7.
        - Rule 4 (Low Desire Guardrail): All scores < 5 -> GUARDRAIL_INTERVENTION minimal response.

        Args:
            user_text: Input query from user.
            desire_scores: Pre-evaluated situational desire scores (1 to 10 scale).
            active_personas: Sequence of active PersonaDefinitions in this session.
            subconscious: Optional Tier 1 SubconsciousStatePayload for master state context.
            recent_speakers: Optional recent speaker history to pick least recent on guardrail.

        Returns:
            TurnRoutingDecision with pattern, primary_speaker_id, secondary_speaker_id,
            dialogue_tone, turn_intent, and reason.

        Raises:
            ValueError: If active_personas is empty.
        """
        if not active_personas:
            raise ValueError("활성화된 컴패니언 페르소나가 없습니다.")

        # 1. Apply Rule 1: Direct Mention Bonus (+4) & Collective Mention Detection
        is_collective = cls.is_collective_mention(user_text) and len(active_personas) >= 2
        scores: list[tuple[PersonaDefinition, int]] = []

        if is_collective:
            mentioned_personas = list(active_personas)
            logger.debug(
                "Collective mention triggered ('%s'): all %d personas boosted",
                user_text,
                len(active_personas),
            )
        else:
            mentioned_personas = [p for p in active_personas if cls.is_directly_mentioned(user_text, p)]

        mentioned_ids = {p.id for p in mentioned_personas}

        for p in active_personas:
            base_score = desire_scores.get(p.id, 5)
            if p.id in mentioned_ids:
                base_score += 4
                logger.debug(
                    "Persona '%s' directly/collectively mentioned: score boosted to %d", p.id, base_score
                )
            scores.append((p, base_score))

        # Sort descending by score. Tie-break: System 2 task first, then persona id.
        scores.sort(
            key=lambda item: (
                -item[1],
                0 if item[0].role == RoleType.SYSTEM_2_TASK else 1,
                item[0].id,
            )
        )

        top1_p, top1_score = scores[0]

        # Case: Single persona session (N=1) -> Always SOLO
        if len(scores) == 1:
            return TurnRoutingDecision(
                pattern=RoutingPattern.SOLO,
                primary_speaker_id=top1_p.id,
                secondary_speaker_id=None,
                dialogue_tone="focused_solo",
                turn_intent="single_persona_session",
                reason=f"{top1_p.name} 단독 세션 발화",
            )

        top2_p, top2_score = scores[1]

        # Rule 0 (Unconditional Multi-Response Guarantee):
        # When user explicitly addresses multiple or all personas ("둘 다", "모두에게", "미우, 베라" 등),
        # NEVER fall back to SOLO or GUARDRAIL silence. Both personas must respond unconditionally!
        is_multi_mention = is_collective or len(mentioned_personas) >= 2
        if is_multi_mention:
            master_state_text = subconscious.master_state if subconscious else ""
            is_crisis = bool(
                CRISIS_KEYWORDS_REGEX.search(master_state_text)
                or CRISIS_KEYWORDS_REGEX.search(user_text)
            )
            if is_crisis:
                if (
                    top1_p.role != RoleType.SYSTEM_1_EMOTIONAL
                    and top2_p.role == RoleType.SYSTEM_1_EMOTIONAL
                ):
                    primary_id = top2_p.id
                    secondary_id = top1_p.id
                    remedy_desc = f"{top2_p.name}(정서 선빵) -> {top1_p.name}(현실 수습)"
                else:
                    primary_id = top1_p.id
                    secondary_id = top2_p.id
                    remedy_desc = f"{top1_p.name}(정서 선빵) -> {top2_p.name}(현실 수습)"

                return TurnRoutingDecision(
                    pattern=RoutingPattern.TAG_TEAM_REMEDIATION,
                    primary_speaker_id=primary_id,
                    secondary_speaker_id=secondary_id,
                    dialogue_tone="empathetic_remediation",
                    turn_intent="emotional_first_strike_then_reality_remedy",
                    reason=f"복수/전체 호명 및 정서 위기 감지: {remedy_desc} (전원 응답 보장)",
                )

            # Normal multi-agent response (collaborative discussion/banter)
            # Both top personas are guaranteed to respond in sequence
            return TurnRoutingDecision(
                pattern=RoutingPattern.DEBATE_BANTER,
                primary_speaker_id=top1_p.id,
                secondary_speaker_id=top2_p.id,
                dialogue_tone="collaborative_banter",
                turn_intent="collective_all_response",
                reason=f"복수/전체 호명('둘 다'/'모두' 등)에 따른 전원 연속 발화 보장: {top1_p.name}({top1_score}점) -> {top2_p.name}({top2_score}점)",
            )

        # Rule 4: Low-desire guardrail (All scores < 5)
        if top1_score < 5:
            # Pick least recent speaker if history available, else top1
            chosen_speaker = top1_p.id
            if recent_speakers:
                recent_list = list(recent_speakers)

                def _last_seen_index(p: PersonaDefinition) -> int:
                    for idx in range(len(recent_list) - 1, -1, -1):
                        if recent_list[idx] == p.id:
                            return idx
                    return -1

                # Sort by last seen index ASC. Tie-break by score, then id.
                sorted_by_recency = sorted(
                    active_personas,
                    key=lambda p: (_last_seen_index(p), desire_scores.get(p.id, 5), p.id),
                )
                chosen_speaker = sorted_by_recency[0].id

            return TurnRoutingDecision(
                pattern=RoutingPattern.GUARDRAIL_INTERVENTION,
                primary_speaker_id=chosen_speaker,
                secondary_speaker_id=None,
                dialogue_tone="minimal_concise",
                turn_intent="guardrail_low_engagement_acknowledgement",
                reason=f"전원 저욕구({top1_score}점 미만) - 사족 방지 및 최소 응답",
            )

        # Direct Mention Priority Guard:
        # Check if an unmentioned persona threatens to silence a directly mentioned persona into SOLO.
        has_direct_mention = len(mentioned_personas) > 0
        top1_is_mentioned = top1_p.id in mentioned_ids

        # Rule 2: Dual high desire (top1 >= 7 and top2 >= 7)
        if top1_score >= 7 and top2_score >= 7:
            # Determine if master is in an emotional crisis
            master_state_text = subconscious.master_state if subconscious else ""
            is_crisis = bool(
                CRISIS_KEYWORDS_REGEX.search(master_state_text)
                or CRISIS_KEYWORDS_REGEX.search(user_text)
            )

            if is_crisis:
                # TAG_TEAM_REMEDIATION: System 1 (emotional) first-strike -> System 2 (task) reality remedy
                # Only invert if top1 is NOT System 1 and top2 IS System 1
                if (
                    top1_p.role != RoleType.SYSTEM_1_EMOTIONAL
                    and top2_p.role == RoleType.SYSTEM_1_EMOTIONAL
                ):
                    primary_id = top2_p.id
                    secondary_id = top1_p.id
                    primary_name = top2_p.name
                    secondary_name = top1_p.name
                    remedy_desc = f"{primary_name}(정서 선빵) -> {secondary_name}(현실 수습)"
                elif (
                    top1_p.role == RoleType.SYSTEM_1_EMOTIONAL
                    and top2_p.role == RoleType.SYSTEM_1_EMOTIONAL
                ):
                    # When both top1 and top2 are System 1 (e.g. Miu score 9, Luna score 8),
                    # preserve natural score ranking and do NOT mislabel either as reality remedy.
                    primary_id = top1_p.id
                    secondary_id = top2_p.id
                    primary_name = top1_p.name
                    secondary_name = top2_p.name
                    remedy_desc = f"{primary_name}(정서 선빵) -> {secondary_name}(정서 공감)"
                elif top1_p.role == RoleType.SYSTEM_1_EMOTIONAL:
                    primary_id = top1_p.id
                    secondary_id = top2_p.id
                    primary_name = top1_p.name
                    secondary_name = top2_p.name
                    remedy_desc = f"{primary_name}(정서 선빵) -> {secondary_name}(현실 수습)"
                else:
                    # Edge Case E5: Neither top persona is System 1; maintain score order
                    logger.warning(
                        "Emotional crisis detected, but neither top persona is System 1; maintaining score order."
                    )
                    primary_id = top1_p.id
                    secondary_id = top2_p.id
                    primary_name = top1_p.name
                    secondary_name = top2_p.name
                    remedy_desc = f"{primary_name} -> {secondary_name}"

                return TurnRoutingDecision(
                    pattern=RoutingPattern.TAG_TEAM_REMEDIATION,
                    primary_speaker_id=primary_id,
                    secondary_speaker_id=secondary_id,
                    dialogue_tone="empathetic_remediation",
                    turn_intent="emotional_first_strike_then_reality_remedy",
                    reason=f"정서 위기 감지: {remedy_desc}",
                )

            # DEBATE_BANTER: Non-crisis dual discussion / banter
            # If top1 was NOT directly mentioned but top2 was, assign primary speaker to the mentioned persona
            if has_direct_mention and not top1_is_mentioned and top2_p.id in mentioned_ids:
                primary_id = top2_p.id
                secondary_id = top1_p.id
                reason_str = f"직접 호명 우선 듀얼 발화: {top2_p.name}(호명 {top2_score}점) -> {top1_p.name}({top1_score}점)"
            else:
                primary_id = top1_p.id
                secondary_id = top2_p.id
                reason_str = f"치열한 듀얼 발화 명분: {top1_p.name}({top1_score}점) -> {top2_p.name}({top2_score}점)"

            return TurnRoutingDecision(
                pattern=RoutingPattern.DEBATE_BANTER,
                primary_speaker_id=primary_id,
                secondary_speaker_id=secondary_id,
                dialogue_tone="collaborative_banter",
                turn_intent="dual_perspective_discussion",
                reason=reason_str,
            )

        # Rule 3: Solo dominance (gap >= 3 or top2 < 7)
        # Direct mention rule: ensure a directly mentioned persona is not silenced into SOLO by an unmentioned persona.
        if has_direct_mention and not top1_is_mentioned:
            # Find the highest scoring directly mentioned persona
            best_mentioned_p = max(mentioned_personas, key=lambda p: desire_scores.get(p.id, 5))

            if top1_score >= 7:
                # Unmentioned persona has strong desire (>= 7), so allow dual participation,
                # but mentioned persona MUST lead as primary speaker and NOT be silenced!
                return TurnRoutingDecision(
                    pattern=RoutingPattern.DEBATE_BANTER,
                    primary_speaker_id=best_mentioned_p.id,
                    secondary_speaker_id=top1_p.id,
                    dialogue_tone="collaborative_banter",
                    turn_intent="direct_mention_lead_dual_discussion",
                    reason=f"{best_mentioned_p.name} 직접 호명 우선 ({top1_p.name} {top1_score}점 듀얼 참여로 단독 침묵 방지)",
                )
            else:
                # Unmentioned persona lacks strong desire; mentioned persona takes SOLO
                return TurnRoutingDecision(
                    pattern=RoutingPattern.SOLO,
                    primary_speaker_id=best_mentioned_p.id,
                    secondary_speaker_id=None,
                    dialogue_tone="focused_solo",
                    turn_intent="single_agent_response",
                    reason=f"{best_mentioned_p.name} 직접 호명 단독 발화",
                )

        return TurnRoutingDecision(
            pattern=RoutingPattern.SOLO,
            primary_speaker_id=top1_p.id,
            secondary_speaker_id=None,
            dialogue_tone="focused_solo",
            turn_intent="single_agent_response",
            reason=f"{top1_p.name} 단독 우세 ({top1_score}점 vs {top2_p.name} {top2_score}점) - 타 캐릭터 침묵/경청",
        )


# Module-level convenience function
evaluate_turn_routing = FloorDirectorGatekeeper.evaluate_turn_routing

__all__ = [
    "FloorDirectorGatekeeper",
    "evaluate_turn_routing",
]
