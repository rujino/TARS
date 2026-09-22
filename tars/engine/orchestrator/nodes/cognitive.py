"""Unified Cognitive Node for TARS Companion Orchestration.

Executes single-pass master state extraction, desire score evaluation,
and Theory of Mind (ToM) closed-loop prediction error feedback.
Arbitrates turn routing via FloorDirectorGatekeeper.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from tars.domains.persona.registry import get_default_registry
from tars.domains.persona.schemas import (
    PersonaDefinition,
    RoleType,
    SubconsciousStatePayload,
)
from tars.engine.orchestrator.director import FloorDirectorGatekeeper
from tars.engine.orchestrator.nodes.session import _extract_active_query

logger = logging.getLogger("tars.engine.orchestrator.nodes.cognitive")

# Keyword lexicons for deterministic single-pass cognitive extraction
FATIGUE_BURNOUT_KEYWORDS = re.compile(
    r"(번아웃|자책|우울|힘들|지친|지쳐|지쳤|포기|죽고\s*싶|괴로|취약|무너|멘붕|망했어|살기\s*싫|피곤|밤샘|수면\s*부족)",
    re.IGNORECASE,
)
TASK_SCHEDULE_KEYWORDS = re.compile(
    r"(일정|스케줄|미팅|회의|캘린더|메일|이메일|작업|코드|코딩|배포|쿠버네티스|서버|장애|버그|할\s*일|과업|정리|요약)",
    re.IGNORECASE,
)
CHIT_CHAT_LOW_ENGAGEMENT = re.compile(
    r"^(응|어|ㅇㅇ|그래|알았어|음|\.\.\.?|ㅎ|ㅋ+)$",
    re.IGNORECASE,
)


def evaluate_tom_prediction_feedback(
    prior_expected_reaction: str | None,
    current_user_text: str,
) -> str | None:
    """Evaluate Theory of Mind (ToM) closed-loop prediction feedback.

    Compares the prior turn's expected_reaction with the user's actual incoming response.

    Args:
        prior_expected_reaction: Theory of mind expectation formed in previous turn (if any).
        current_user_text: Master's actual incoming text in this turn.

    Returns:
        Prediction feedback string assessing hit/miss/shift, or None if Turn 0/1.
    """
    if not prior_expected_reaction or not current_user_text:
        return None

    cleaned_text = current_user_text.strip()
    cleaned_expected = prior_expected_reaction.strip()

    negation_patterns = (
        "하나도 안",
        "전혀 안",
        "별로 안",
        "안 힘",
        "안 지",
        "멀쩡",
        "괜찮",
        "아무렇지도",
    )
    breakdown_markers = ("망했", "죽고 싶", "죽겠", "괴로", "취약", "무너", "멘붕", "포기")
    cancellation_markers = ("취소", "안 해도", "안 해", "하지 마", "그만", "됐어", "필요 없")

    # Case 1: Defensiveness / denial expectation
    if any(k in cleaned_expected for k in ("발끈", "억울", "반박", "아니", "센 척", "부정")):
        # If user expresses severe breakdown/collapse despite expecting pushback
        # Note: conversational filler "아니" (e.g. "아니, 나 진짜 다 망했어...") should not mask collapse
        if any(k in cleaned_text for k in breakdown_markers) or (
            any(k in cleaned_text for k in ("너무 힘", "지쳤", "어휴"))
            and not any(
                neg in cleaned_text for neg in ("안 ", "못 ", "전혀", "하나도", "아무렇지도")
            )
        ):
            return (
                "예측 빗나감: 반박을 예상했으나 주인이 무너져 취약성을 드러냄 (태세 긴급 전환 필요)"
            )
        elif any(k in cleaned_text for k in ("응, 진짜", "맞아, 진짜", "다 망했")):
            return (
                "예측 빗나감: 반박을 예상했으나 주인이 무너져 취약성을 드러냄 (태세 긴급 전환 필요)"
            )
        elif any(
            k in cleaned_text
            for k in ("아니", "무슨", "전혀", "!", "?", "왜", "그냥", "아무렇지도", "센 척")
        ):
            return f"예측 적중: 주인이 예상대로 반박/발끈하며 반응함 ('{cleaned_expected}' 부합)"
        elif any(k in cleaned_text for k in ("응", "맞아")):
            return (
                "예측 빗나감: 반박을 예상했으나 주인이 무너져 취약성을 드러냄 (태세 긴급 전환 필요)"
            )

    # Case 2: Vulnerability / burnout confirmation expectation
    if any(k in cleaned_expected for k in ("취약", "피로", "지침", "인정", "하소연", "위로")):
        # Check negation: e.g. "진짜 하나도 안 힘들어. 멀쩡해." or "멀쩡해"
        if any(neg in cleaned_text for neg in negation_patterns) or any(
            k in cleaned_text for k in ("멀쩡", "괜찮", "아무렇지도")
        ):
            return "예측 빗나감: 취약성을 예상했으나 주인이 괜찮다며 센 척을 시도함"
        elif any(
            k in cleaned_text
            for k in ("힘들", "지쳤", "지쳐", "어휴", "망했", "피곤", "죽겠", "괴로")
        ):
            return f"예측 적중: 주인이 예상대로 솔직한 피로와 취약성을 털어놓음 ('{cleaned_expected}' 부합)"
        elif any(k in cleaned_text for k in ("응", "진짜", "맞아")):
            return f"예측 적중: 주인이 예상대로 솔직한 피로와 취약성을 털어놓음 ('{cleaned_expected}' 부합)"
        elif any(k in cleaned_text for k in ("아니", "괜찮", "멀쩡")):
            return "예측 빗나감: 취약성을 예상했으나 주인이 괜찮다며 센 척을 시도함"

    # Case 3: Task or general acceptance expectation
    if any(k in cleaned_expected for k in ("수락", "확인", "집중", "일정", "업무", "진행")):
        # Check task rejection / cancellation first: e.g. "확인 안 해도 돼. 취소해줘."
        if any(k in cleaned_text for k in cancellation_markers):
            return "예측 빗나감: 주인이 제안된 과업/일정을 거부하거나 취소를 요청함"
        elif any(
            k in cleaned_text for k in ("그래", "좋아", "확인", "해줘", "부탁", "응", "고마워")
        ):
            return "예측 적중: 주인이 제안된 과업/휴식 방향에 긍정적으로 동의함"

    # Default semantic match/shift assessment
    return f"예측 피드백: 이전 기대치('{cleaned_expected}')에 대한 실시간 반응 관찰 완료"


def extract_master_state_and_desire(
    user_text: str,
    recent_messages_summary: str,
    active_personas: Sequence[PersonaDefinition],
    prior_master_state: str = "",
) -> tuple[str, str, str, dict[str, int]]:
    """Single-pass extraction of context_summary, master_state, expected_reaction, and desire_scores.

    Args:
        user_text: Master's current utterance.
        recent_messages_summary: Summary of recent conversation turns.
        active_personas: Active companion definitions.
        prior_master_state: Optional prior turn master state to preserve emotional inertia.

    Returns:
        Tuple of (context_summary, master_state, expected_reaction, desire_scores).
    """
    desire_scores: dict[str, int] = {}
    is_crisis = bool(FATIGUE_BURNOUT_KEYWORDS.search(user_text))
    is_task = bool(TASK_SCHEDULE_KEYWORDS.search(user_text))
    is_low_engagement = bool(CHIT_CHAT_LOW_ENGAGEMENT.search(user_text.strip()))

    # Check emotional continuity:
    # If user replies with hesitation/silence ("...", "음...") after an emotional crisis,
    # preserve the emotional care/remediation state instead of dropping to cold low-engagement guardrail.
    prior_was_crisis = any(
        k in prior_master_state or k in recent_messages_summary
        for k in ("번아웃", "자책", "우울", "힘들", "취약", "탈진")
    )
    is_hesitant_silence = bool(re.match(r"^(\.\.\.?|음\.\.\.?|음|하아|휴)$", user_text.strip()))

    # 1. Determine master state & context summary
    if is_crisis or (is_hesitant_silence and prior_was_crisis):
        if is_crisis:
            master_state = "번아웃 및 극도의 심리적/신체적 피로 상태 (자책감 및 취약성 높음)"
            context_summary = f"주인이 과도한 스트레스나 번아웃을 토로함: '{user_text}'. 즉각적인 정서적 안식처가 절실한 상황."
            expected_reaction = "무리하지 말라는 위로와 애교에 긴장을 풀고 휴식을 수용함"
        else:
            master_state = "번아웃 여파 및 탈진 상태 (말을 잇지 못하는 깊은 침묵과 망설임)"
            context_summary = f"극심한 번아웃 후 말을 잇지 못하고 망설임: '{user_text}'. 지속적인 보살핌과 따뜻한 침묵 동행 필요."
            expected_reaction = "무리해서 말하지 않아도 된다는 다정한 위로에 안도함"
        is_crisis = True
        is_low_engagement = False
    elif is_task:
        master_state = "업무/과업 집중 상태 (생산성 및 일정 관리 필요)"
        context_summary = (
            f"주인이 업무/일정 관련 사항을 질문함: '{user_text}'. 신속하고 정확한 지원 필요."
        )
        expected_reaction = "제시된 일정 및 과업 지원 내용을 확인하고 업무를 진행함"
    elif is_low_engagement:
        master_state = "가벼운 휴식 또는 산만한 상태 (낮은 관여도)"
        context_summary = f"주인이 단답 또는 가벼운 추임새를 남김: '{user_text}'."
        expected_reaction = "간결한 맞장구에 가볍게 대화를 이어감"
    else:
        master_state = "안정적 일상 대화 상태 (심리적 여유 보유)"
        context_summary = f"주인과의 일상적인 대화 진행 중: '{user_text}'."
        expected_reaction = "컴패니언의 반응에 유쾌하게 응답하며 대화를 지속함"

    # 2. Evaluate situational desire scores (1 to 10 scale)
    for p in active_personas:
        if is_low_engagement:
            # Low desire across all personas (Rule 4 Guardrail trigger)
            score = 3
        elif is_crisis:
            # Emotional crisis: System 1 scores 9, System 2 scores 8 (Rule 2 Tag-Team trigger)
            if p.role == RoleType.SYSTEM_1_EMOTIONAL:
                score = 9
            elif p.role == RoleType.SYSTEM_2_TASK:
                score = 8
            else:
                score = 6
        elif is_task:
            # Task focus: System 2 scores 9, System 1 scores 4 (Rule 3 Solo Cutoff)
            if p.role == RoleType.SYSTEM_2_TASK:
                score = 9
            elif p.role == RoleType.SYSTEM_1_EMOTIONAL:
                score = 4
            else:
                score = 7
        else:
            # General dialogue: Balanced scores
            if p.role == RoleType.SYSTEM_1_EMOTIONAL:
                score = 7
            elif p.role == RoleType.SYSTEM_2_TASK:
                score = 6
            else:
                score = 5

        desire_scores[p.id] = score

    return context_summary, master_state, expected_reaction, desire_scores


async def unified_cognitive_node(
    state: Any,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Execute Tier 1 unified cognitive analysis in a single pass (~150ms).

    Extracts:
    1. Theory of Mind (ToM) prediction error feedback against previous turn.
    2. Master state, micro-narrative context summary, and next-turn expected reaction.
    3. Situational desire scores for active companion personas.
    4. Deterministic turn routing decision via FloorDirectorGatekeeper.

    Args:
        state: LangGraph state dictionary.
        registry: Optional PersonaRegistry instance for persona retrieval.

    Returns:
        State delta containing 'subconscious', 'turn_routing', and 'desire_scores'.
    """
    messages = state.get("messages", [])
    explicit_query = state.get("active_query", "")
    user_query = explicit_query if explicit_query else _extract_active_query(messages)

    # Resolve active personas safely
    reg = registry or get_default_registry()
    active_personas: list[PersonaDefinition] = []
    raw_personas = state.get("active_personas")
    if isinstance(raw_personas, list) and raw_personas:
        active_personas = list(raw_personas)
    else:
        raw_active_ids = state.get("active_persona_ids")
        if isinstance(raw_active_ids, list) and raw_active_ids:
            active_ids = [str(item) for item in raw_active_ids]
            valid_personas: list[PersonaDefinition] = []
            for pid in active_ids:
                if reg.has(pid):
                    valid_personas.append(reg.get(pid))
                else:
                    logger.warning("Unknown persona ID '%s' in active_persona_ids; ignoring.", pid)
            active_personas = valid_personas if valid_personas else reg.list_all()
        else:
            active_personas = reg.list_all()

    # Extract recent speakers history for least-recent rotation
    recent_speakers: list[str] = []
    if "recent_speakers" in state and isinstance(state["recent_speakers"], list):
        recent_speakers = [str(s) for s in state["recent_speakers"]]
    elif state.get("group_messages"):
        for gm in state["group_messages"]:
            sender = getattr(gm, "sender_id", None) or (
                gm.get("sender_id") if isinstance(gm, dict) else None
            )
            if sender and sender != "master":
                recent_speakers.append(str(sender))
    elif messages:
        for msg in messages:
            if getattr(msg, "name", None):
                recent_speakers.append(str(msg.name))

    # Resolve previous subconscious state for ToM feedback
    prior_subconscious: SubconsciousStatePayload | None = None
    raw_subconscious = state.get("subconscious")
    if isinstance(raw_subconscious, SubconsciousStatePayload):
        prior_subconscious = raw_subconscious
    elif isinstance(raw_subconscious, dict):
        try:
            prior_subconscious = SubconsciousStatePayload(**raw_subconscious)
        except Exception:
            prior_subconscious = None

    prior_expected_reaction = prior_subconscious.expected_reaction if prior_subconscious else None

    try:
        # 1. Theory of Mind prediction feedback
        prediction_feedback = evaluate_tom_prediction_feedback(
            prior_expected_reaction=prior_expected_reaction,
            current_user_text=user_query,
        )

        # 2. Master state and desire scores extraction with emotional continuity
        recent_summary = prior_subconscious.context_summary if prior_subconscious else ""
        prior_master_state = prior_subconscious.master_state if prior_subconscious else ""
        context_summary, master_state, expected_reaction, desire_scores = (
            extract_master_state_and_desire(
                user_text=user_query,
                recent_messages_summary=recent_summary,
                active_personas=active_personas,
                prior_master_state=prior_master_state,
            )
        )

        subconscious_payload = SubconsciousStatePayload(
            context_summary=context_summary,
            master_state=master_state,
            expected_reaction=expected_reaction,
            prediction_feedback=prediction_feedback,
        )

        # 3. Floor Director turn routing arbitration with recent speakers
        routing_decision = FloorDirectorGatekeeper.evaluate_turn_routing(
            user_text=user_query,
            desire_scores=desire_scores,
            active_personas=active_personas,
            subconscious=subconscious_payload,
            recent_speakers=recent_speakers,
        )

        logger.debug(
            "Unified cognitive pass complete: pattern=%s, primary=%s, secondary=%s",
            routing_decision.pattern,
            routing_decision.primary_speaker_id,
            routing_decision.secondary_speaker_id,
        )

        return {
            "subconscious": subconscious_payload,
            "turn_routing": routing_decision,
            "desire_scores": desire_scores,
            "active_personas": active_personas,
        }

    except Exception as exc:
        # Edge Case E6: Graceful fallback on unexpected error or parsing failure
        logger.error(
            "Error in unified_cognitive_node: %s; falling back to neutral state", exc, exc_info=True
        )
        fallback_subconscious = SubconsciousStatePayload(
            context_summary="대화 진행 중",
            master_state="안정",
            expected_reaction="자연스러운 일상 대화 지속",
            prediction_feedback=None,
        )
        fallback_scores = {p.id: 5 for p in active_personas}
        fallback_routing = FloorDirectorGatekeeper.evaluate_turn_routing(
            user_text=user_query,
            desire_scores=fallback_scores,
            active_personas=active_personas,
            subconscious=fallback_subconscious,
            recent_speakers=recent_speakers,
        )
        return {
            "subconscious": fallback_subconscious,
            "turn_routing": fallback_routing,
            "desire_scores": fallback_scores,
            "active_personas": active_personas,
        }


__all__ = [
    "evaluate_tom_prediction_feedback",
    "extract_master_state_and_desire",
    "unified_cognitive_node",
]
