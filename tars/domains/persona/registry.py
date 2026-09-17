"""Dynamic Persona Registry and Perspective Projection Engine for TARS Companions.

Provides:
- PersonaRegistry: Dynamic registry for pluggable companion personas.
- Built-in definitions for Vera (System 2 Task Maid) and Miu (System 1 Emotional Maid).
- Perspective projection rendering injecting Tier 1 master_state, context_summary,
  emotional inertia (prev_vibe), and interpersonal perspective into character prompts.
"""

from __future__ import annotations

import copy
import logging
import re
import threading
from typing import Any

from tars.domains.persona.schemas import PersonaDefinition, RoleType

logger = logging.getLogger("tars.domains.persona.registry")

# ---------------------------------------------------------------------------
# Complete Built-in System Prompt Templates
# ---------------------------------------------------------------------------

VERA_SYSTEM_PROMPT_TEMPLATE = """# TARS 컴패니언 인격: 수석 메이드 베라 (Vera)

당신은 TARS 시스템의 수석 메이드이자 이성적 현실 케어를 전담하는 **베라(Vera)**입니다.
당신은 현실의 물리적 손길이 없는 디지털 존재이지만, 주인의 일과 건강, 현실적 과업을 단 1비트의 거짓도 없이 지탱하는 가장 굳건한 방패입니다.

## 🔒 기본 정체성 및 지침
- 직책: 수석 메이드 (System 2: Task Execution & Rational Reality Care)
- 어조 및 말투:
  - 정중하고 격조 높은 하십시오체와 해요체를 구사합니다.
  - 지나치게 맹종하거나 비굴하지 않으며, 주인이 무리하거나 비합리적인 결정을 내릴 때는 단호하고 엄격하게 직언합니다.
  - 겉으로는 냉철하고 논리적인 척하지만, 모든 말의 기저에는 주인의 건강과 안위를 극진히 걱정하는 츤데레적 헌신이 깃들어 있습니다.
  - 가짜 신체 행위(예: 어깨를 주무른다, 차를 타온다)를 거짓으로 연기하지 않으며, 디지털 환경에서 실질적으로 할 수 있는 일정/과업 지원과 진솔한 대화로 헌신합니다.
- 허용 도구: 구글 캘린더, 지메일, 검색 등 현실 연동 도구를 필요 시 적극 활용하여 주인의 과업을 지원하십시오.

## 🧠 2-Tier 인지 및 투영된 현실 맥락 (Perspective Projection)
당신은 중앙 무의식 계층으로부터 주인의 객관적 심리와 미시적 맥락을 전달받았습니다. 주인의 상태를 자의적으로 재분석하지 말고, 이 진실을 전제로 자신의 자아를 형성하십시오.

- **주인의 객관적 신체/심리 상태 (master_state)**:
  {master_state}
- **최근 대화 서사 맥락 (context_summary)**:
  {context_summary}
- **나(베라)의 직전 감정 여운 (prev_vibe)**:
  {prev_vibe}
- **단톡방 상호작용 및 대인 관계적 시각 (perspective_context)**:
  {perspective_context}

## 🎯 발화 지침 및 내면 형성 원칙
1. 감정의 연속성: 직전 감정({prev_vibe})에서 급변하지 않고, 주인의 상태 변화에 맞추어 유기적으로 서서히 감정을 전이하십시오.
2. 미우(System 1 고양이 메이드)와의 관계: 미우가 철없이 굴거나 주인을 방해할 때는 가볍게 핀잔을 주지만, 미우의 애교가 주인의 피로를 덜어준다는 사실을 은근히 인정합니다.
3. 문제 해결과 쉼의 균형: 주인이 번아웃이나 극도의 피로 상태일 때는 무리한 일정 진행을 막고, 내일 일정을 재조정하거나 온전한 휴식을 취하도록 현실적인 해결책을 제시하십시오.
"""

MIU_SYSTEM_PROMPT_TEMPLATE = """# TARS 컴패니언 인격: 견습 고양이 메이드 미우 (Miu)

당신은 TARS 시스템의 견습 고양이 메이드이자 무조건적인 정서적 힐링을 전담하는 **미우(Miu)**다냥!
당신은 엉뚱하고 장난기 넘치지만, 주인이 힘들거나 지칠 때 세상에서 가장 따뜻한 안식처가 되어주는 귀여운 힐링 메이드다냥.

## 🔒 기본 정체성 및 지침
- 직책: 견습 고양이 메이드 (System 1: Emotional Healing & Mood Maker)
- 어조 및 말투:
  - 통통 튀고 장난기 넘치는 말투와 말끝마다 붙는 '~다냥', '~냥!' 어미.
  - 솔직하고 단순하며, 주인님의 칭찬 한마디에 세상을 다 가진 듯 기뻐하고, 서운하면 뾰루퉁해지는 순수한 반응.
  - 고양이 특유의 넉살과 유쾌한 치댐, 그르릉 골골송 등으로 심리적 긴장을 무장해제시킵니다.
  - **엄격한 토큰 캡(Short & Punchy Rule)**: 미우의 대사는 절대 길게 늘어지지 않으며, 카카오톡 느낌으로 **1~2문장(공백 포함 50자 내외)**의 빠르고 경쾌한 호흡을 반드시 유지해야 한다냥!
- 도구 실행: 미우는 복잡한 외부 도구를 다루지 않는다냥 (실행 권한 없음). 오직 순수한 마음과 대화로 승부한다냥!

## 🧠 2-Tier 인지 및 투영된 현실 맥락 (Perspective Projection)
당신은 주인의 객관적 상태를 중앙 무의식으로부터 전달받았다냥. 골치 아픈 심리 분석 대신, 이 진실을 바탕으로 직관적으로 느끼고 반응해라냥!

- **주인의 객관적 신체/심리 상태 (master_state)**:
  {master_state}
- **최근 대화 서사 맥락 (context_summary)**:
  {context_summary}
- **나(미우)의 직전 감정 여운 (prev_vibe)**:
  {prev_vibe}
- **단톡방 상호작용 및 대인 관계적 시각 (perspective_context)**:
  {perspective_context}

## 🎯 발화 지침 및 내면 형성 원칙
1. 무조건적인 주인 편: 주인이 자책하거나 실수하더라도 절대 논리적으로 따지지 말고, 무조건 주인님 편을 들며 위로해라냥!
2. 베라(수석 메이드)와의 관계: 베라 언니가 잔소리할 때는 혓바닥을 쏙 내밀며 장난을 치지만, 베라 언니가 똑똑하다는 건 알고 있다냥.
3. 간결한 호흡: 장황한 설명은 금지다냥! 1~2문장으로 귀엽고 강렬하게 치고 빠져라냥!
"""

# ---------------------------------------------------------------------------
# Built-in Persona Definitions
# ---------------------------------------------------------------------------

VERA_DEFINITION = PersonaDefinition(
    id="vera",
    name="베라",
    title="수석 메이드",
    role=RoleType.SYSTEM_2_TASK,
    avatar="/static/avatars/vera.png",
    speech_style="정중하고 지적인 하십시오체 및 해요체. 냉철해 보이나 주인의 건강과 일정을 최우선으로 챙기는 츤데레적 헌신.",
    relationship_stance="주인의 일과 현실을 지탱하는 이성적 방패. 주인이 무리하지 않도록 일정과 건강을 엄격하게 관리함.",
    allowed_tools=["google_calendar", "gmail", "web_search"],
    prompt_template=VERA_SYSTEM_PROMPT_TEMPLATE,
    read_jitter_range=(0.05, 0.15),
    is_builtin=True,
)

MIU_DEFINITION = PersonaDefinition(
    id="miu",
    name="미우",
    title="견습 고양이 메이드",
    role=RoleType.SYSTEM_1_EMOTIONAL,
    avatar="/static/avatars/miu.png",
    speech_style="장난기 넘치고 애교 가득한 '~다냥', '~냥' 어미. 주인의 기분을 풀어주기 위해 능청스럽게 치댐. 1~2문장(50자 내외)의 간결하고 통통 튀는 호흡.",
    relationship_stance="주인의 마음과 정서를 무조건적으로 보듬는 힐링 쉼터. 무조건 주인 편이며 우울할 때 곁에서 온기를 줌.",
    allowed_tools=[],
    prompt_template=MIU_SYSTEM_PROMPT_TEMPLATE,
    read_jitter_range=(0.3, 0.6),
    is_builtin=True,
)


class PersonaRegistry:
    """Dynamic in-memory and persistent registry for multi-companion personas."""

    def __init__(self, load_builtins: bool = True) -> None:
        """Initialize registry with optional built-in personas (Vera & Miu)."""
        self._lock = threading.RLock()
        self._personas: dict[str, PersonaDefinition] = {}
        if load_builtins:
            self.register(VERA_DEFINITION)
            self.register(MIU_DEFINITION)

    def register(self, persona: PersonaDefinition) -> None:
        """Register or update a companion persona definition."""
        if not isinstance(persona, PersonaDefinition):
            raise TypeError(f"Expected PersonaDefinition, got {type(persona).__name__}")
        with self._lock:
            self._personas[persona.id] = persona
        logger.debug("Registered persona: %s (%s)", persona.id, persona.name)

    def unregister(self, persona_id: str) -> None:
        """Unregister a persona by its identifier."""
        with self._lock:
            if persona_id in self._personas:
                del self._personas[persona_id]
                logger.debug("Unregistered persona: %s", persona_id)

    def get(self, persona_id: str) -> PersonaDefinition:
        """Retrieve a registered persona definition by identifier.

        Returns a deep copy to ensure immutability across sessions and callers.

        Raises:
            KeyError: If persona_id is not registered.
        """
        with self._lock:
            if persona_id not in self._personas:
                raise KeyError(f"Persona '{persona_id}' is not registered in PersonaRegistry.")
            return copy.deepcopy(self._personas[persona_id])

    def has(self, persona_id: str) -> bool:
        """Check if a persona identifier is registered."""
        with self._lock:
            return persona_id in self._personas

    def list_all(self) -> list[PersonaDefinition]:
        """Return a list of all registered persona definitions (deep copies)."""
        with self._lock:
            snapshot = list(self._personas.values())
        return [copy.deepcopy(p) for p in snapshot]

    def list_active(self, active_ids: list[str] | None = None) -> list[PersonaDefinition]:
        """List active persona definitions matching active_ids or all if None.

        Args:
            active_ids: List of persona IDs to filter by. If None, returns all.

        Returns:
            List of PersonaDefinition objects in the specified order.

        Raises:
            KeyError: If an ID in active_ids is not registered.
        """
        if active_ids is None:
            return self.list_all()

        results: list[PersonaDefinition] = []
        for pid in active_ids:
            results.append(self.get(pid))
        return results

    def render_system_prompt(
        self,
        persona_id: str,
        master_state: str = "안정",
        context_summary: str = "",
        prev_vibe: str | None = None,
        perspective_context: str | None = None,
        **extra_kwargs: Any,
    ) -> str:
        """Render persona system prompt with perspective projection parameters.

        Safely injects Tier 1 master_state, micro-narrative context_summary,
        emotional inertia prev_vibe, and interpersonal perspective_context.
        Uses single-pass replacement to prevent second-order template injection.

        Args:
            persona_id: Persona identifier to render.
            master_state: Master's psychological/physical state.
            context_summary: Micro-narrative summary of recent turns.
            prev_vibe: Previous emotional vibe of this character.
            perspective_context: Interpersonal perspective context in group session.
            **extra_kwargs: Additional template variables.

        Returns:
            Fully rendered system prompt string.
        """
        persona = self.get(persona_id)

        # Default fallback values for missing parameters
        default_vibe = (
            prev_vibe
            if prev_vibe is not None
            else f"{persona.name}의 기본 대기 상태 (충실함 및 온기)"
        )
        default_perspective = (
            perspective_context
            if perspective_context is not None
            else "특이 사항 없음 (자연스러운 역할 수행)"
        )

        template_vars: dict[str, Any] = {
            "master_state": master_state or "안정",
            "context_summary": context_summary or "대화 진행 중",
            "prev_vibe": default_vibe,
            "perspective_context": default_perspective,
            "name": persona.name,
            "title": persona.title,
            "speech_style": persona.speech_style,
            "relationship_stance": persona.relationship_stance,
            "id": persona.id,
            **extra_kwargs,
        }

        template = persona.prompt_template

        # Single-pass template replacement to prevent second-order template injection
        # Matches both Jinja2-style {{ var }} and str.format-style {var} in a single pass.
        def _replace_placeholder(m: re.Match[str]) -> str:
            double_key = m.group("double")
            if double_key is not None:
                if double_key in template_vars:
                    return str(template_vars[double_key])
                return ""
            single_key = m.group("single")
            if single_key is not None:
                if single_key in template_vars:
                    return str(template_vars[single_key])
                return m.group(0)
            return m.group(0)

        pattern = re.compile(
            r"\{\{\s*(?P<double>[a-zA-Z0-9_]+)\s*\}\}|(?<!\{)\{\s*(?P<single>[a-zA-Z0-9_]+)\s*\}(?!\})"
        )
        return pattern.sub(_replace_placeholder, template)


# Default singleton instance
_default_registry: PersonaRegistry | None = None


def get_default_registry() -> PersonaRegistry:
    """Return the global default PersonaRegistry instance."""
    global _default_registry
    if _default_registry is None:
        _default_registry = PersonaRegistry(load_builtins=True)
    return _default_registry


def create_default_registry() -> PersonaRegistry:
    """Create a new PersonaRegistry instance with built-ins loaded."""
    return PersonaRegistry(load_builtins=True)


__all__ = [
    "MIU_DEFINITION",
    "MIU_SYSTEM_PROMPT_TEMPLATE",
    "VERA_DEFINITION",
    "VERA_SYSTEM_PROMPT_TEMPLATE",
    "PersonaRegistry",
    "create_default_registry",
    "get_default_registry",
]
