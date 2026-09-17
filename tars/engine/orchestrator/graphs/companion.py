"""LangGraph Companion Pipeline for TARS Cognitive Companion Engine.

Assembles the 2-tier cognitive companion architecture:
START -> session_node -> slicer_node -> unified_cognitive_node -> companion_dispatch_node -> postprocess_node -> END

Supports both 1:1 solo sessions (N=1) and multi-companion group chats (e.g. Vera & Miu)
with deterministic turn arbitration, Theory of Mind, and perspective projection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from tars.domains.knowledge.spec.schemas import OKFDocument
from tars.domains.persona.registry import PersonaRegistry, get_default_registry
from tars.domains.persona.schemas import (
    CharacterInnerState,
    GroupChatMessage,
    PersonaDefinition,
    RoutingPattern,
    SubconsciousStatePayload,
    TurnRoutingDecision,
)
from tars.engine.adapters.router import HybridLLMRouter
from tars.engine.orchestrator.nodes.cognitive import unified_cognitive_node
from tars.engine.orchestrator.nodes.session import _extract_active_query

if TYPE_CHECKING:
    from fastapi import BackgroundTasks
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph
    from sqlalchemy.ext.asyncio import AsyncSession

    from tars.core.session.manager import SmartSessionManager
    from tars.domains.knowledge.slicer.engine import DynamicSlicerEngine
    from tars.domains.knowledge.storage.manager import FileStorageManager

logger = logging.getLogger("tars.engine.orchestrator.graphs.companion")


class CompanionState(TypedDict, total=False):
    """Complete LangGraph state schema for Cognitive Companion Engine."""

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    session_id: str
    active_query: str
    mode: str
    active_persona_ids: list[str]
    active_personas: list[PersonaDefinition]
    subconscious: SubconsciousStatePayload | None
    turn_routing: TurnRoutingDecision | None
    desire_scores: dict[str, int]
    persona_states: dict[str, CharacterInnerState]
    group_messages: list[GroupChatMessage]
    relevant_wikis: list[OKFDocument]
    system_prompt: str
    final_response: str
    error_message: str | None
    engine: str | None
    model_name: str | None


# ---------------------------------------------------------------------------
# Node Implementations
# ---------------------------------------------------------------------------


async def companion_session_node(
    state: CompanionState,
    registry: PersonaRegistry | None = None,
) -> dict[str, Any]:
    """Initialize session parameters and resolve active personas."""
    reg = registry or get_default_registry()
    messages = state.get("messages", [])
    extracted_query = _extract_active_query(messages)
    query = extracted_query if extracted_query else state.get("active_query", "")
    active_ids = state.get("active_persona_ids")

    if active_ids:
        valid_personas = [reg.get(pid) for pid in active_ids if reg.has(pid)]
        active_personas = valid_personas if valid_personas else reg.list_active(["vera", "miu"])
    else:
        active_personas = reg.list_active(["vera", "miu"])
    active_ids = [p.id for p in active_personas]

    persona_states = dict(state.get("persona_states") or {})

    return {
        "active_query": query,
        "active_persona_ids": active_ids,
        "active_personas": active_personas,
        "persona_states": persona_states,
    }


async def companion_slicer_node(
    state: CompanionState,
    slicer: DynamicSlicerEngine | None = None,
) -> dict[str, Any]:
    """Slice relevant OKF context and thought nodes."""
    user_id = state.get("user_id", "")
    query = state.get("active_query", "")

    if not user_id or slicer is None:
        return {"relevant_wikis": state.get("relevant_wikis", [])}

    try:
        relevant_wikis: list[OKFDocument] = await slicer.slice_context(
            user_id=user_id,
            query=query,
            token_budget=1500,
        )
        return {"relevant_wikis": relevant_wikis}
    except Exception as exc:
        logger.error("Error during companion slicing: %s", exc, exc_info=True)
        return {"relevant_wikis": []}


def _synthesize_inner_state(
    persona: PersonaDefinition | str | None = None,
    routing: TurnRoutingDecision | None = None,
    subconscious: SubconsciousStatePayload | None = None,
    prev_vibe: str | None = None,
    user_query: str = "",
    is_secondary: bool = False,
    *,
    persona_id: str | None = None,
    primary_response: str | None = None,
    **kwargs: Any,
) -> CharacterInnerState:
    """Synthesize autonomous CharacterInnerState (my_vibe and my_agenda) purely from state.

    Computes Tier 2 conscious inner agency without any dialogue f-strings or synthetic text.
    Maintains emotional continuity (prev_vibe) and aligns persona agendas with routing patterns.
    """
    # 1. Resolve speaker persona identifier
    target_id: str
    if persona_id:
        target_id = persona_id
    elif persona is not None:
        target_id = persona.id if hasattr(persona, "id") else str(persona)
    elif routing is not None:
        target_id = (
            routing.secondary_speaker_id
            if (is_secondary and routing.secondary_speaker_id)
            else routing.primary_speaker_id
        )
    else:
        target_id = "vera"

    # 2. Resolve routing pattern & tone
    pattern = routing.pattern if routing is not None else RoutingPattern.SOLO

    # 3. Deterministic vibe and agenda synthesis
    if target_id == "miu":
        if pattern == RoutingPattern.TAG_TEAM_REMEDIATION:
            my_vibe = "주인님을 향한 깊은 안쓰러움과 애틋한 온기 (피로 완화 집중)"
            my_agenda = "무조건적인 편들기와 골골송으로 심리적 긴장 풀어주기"
        elif pattern == RoutingPattern.DEBATE_BANTER:
            my_vibe = "장난기 넘치고 신나는 활기 80%"
            my_agenda = "베라 언니에게 딴지 걸며 주인님 관심 집중시키기"
        elif pattern == RoutingPattern.GUARDRAIL_INTERVENTION:
            my_vibe = "나른하고 차분한 대기 상태"
            my_agenda = "가볍게 눈을 맞추며 주인의 다음 지시 기다리기"
        else:  # SOLO or default
            my_vibe = f"{prev_vibe}의 여운을 이어받은 경쾌함" if prev_vibe else "밝고 경쾌한 충실함"
            my_agenda = "주인님 말씀에 귀 기울이고 신나게 화답하기"

    elif target_id == "vera":
        if pattern == RoutingPattern.TAG_TEAM_REMEDIATION:
            my_vibe = "주인의 안위에 대한 깊은 우려와 차분한 츤데레적 헌신"
            my_agenda = "무리한 일정 취소 및 침대로 안전하게 유도하기"
        elif pattern == RoutingPattern.DEBATE_BANTER:
            my_vibe = "이성적이고 철저한 수석 메이드의 평정심"
            my_agenda = "정확한 팩트 전달 및 미우의 철없는 행동 부드럽게 단속"
        elif pattern == RoutingPattern.GUARDRAIL_INTERVENTION:
            my_vibe = "단정한 대기 상태"
            my_agenda = "불필요한 사족을 배제하고 주인님의 다음 지시 대기"
        else:  # SOLO or default
            my_vibe = f"{prev_vibe}의 여운 속에서 정돈된 차분함" if prev_vibe else "성실하고 차분함"
            my_agenda = "정확하고 지적인 현실 과업 지원"

    else:
        tone = getattr(routing, "dialogue_tone", "neutral") if routing else "neutral"
        intent = getattr(routing, "turn_intent", "dialogue") if routing else "dialogue"
        my_vibe = f"{target_id}의 고유 기분 상태 ({tone})"
        my_agenda = f"{intent}에 따른 성실한 응답"

    return CharacterInnerState(
        speaker_id=target_id,
        my_vibe=my_vibe,
        my_agenda=my_agenda,
    )


async def companion_dispatch_node(
    state: CompanionState,
    registry: PersonaRegistry | None = None,
    router: HybridLLMRouter | None = None,
) -> dict[str, Any]:
    """Execute Tier 2 conscious companion dispatching and genuine LLM generation.

    Zero Mock Policy: Completely eliminates canned dialogue templates.
    Companions independently infer responses via HybridLLMRouter using
    dynamically rendered system prompts from PersonaRegistry with
    Theory of Mind, perspective context, and emotional inertia injected.
    """
    reg = registry or get_default_registry()
    subconscious = state.get("subconscious")
    routing = state.get("turn_routing")
    user_query = state.get("active_query", "")
    session_id = state.get("session_id", "default_companion_session")
    active_personas = state.get("active_personas") or reg.list_all()
    persona_map = {p.id: p for p in active_personas}
    persona_states = dict(state.get("persona_states") or {})
    group_messages = list(state.get("group_messages") or [])

    if not subconscious:
        subconscious = SubconsciousStatePayload(
            context_summary="대화 진행 중",
            master_state="안정",
            expected_reaction=None,
            prediction_feedback=None,
        )

    if not routing:
        fallback_speaker_id = active_personas[0].id if active_personas else "vera"
        routing = TurnRoutingDecision(
            pattern=RoutingPattern.SOLO,
            primary_speaker_id=fallback_speaker_id,
            dialogue_tone="neutral",
            turn_intent="dialogue",
        )

    if router is None:
        raise ValueError(
            "HybridLLMRouter must be provided to companion_dispatch_node for authentic LLM inference."
        )

    out_messages: list[BaseMessage] = []
    response_texts: list[str] = []
    executed_engine = "gemini"
    executed_model = "gemini-3.7-flash"

    # 1. Primary Speaker Generation
    primary_id = routing.primary_speaker_id
    primary_p = persona_map.get(primary_id) or reg.get(primary_id)
    prev_vibe_primary = persona_states[primary_id].my_vibe if primary_id in persona_states else None

    primary_inner = _synthesize_inner_state(
        persona=primary_p,
        routing=routing,
        subconscious=subconscious,
        prev_vibe=prev_vibe_primary,
        persona_id=primary_id,
        user_query=user_query,
        is_secondary=False,
    )
    persona_states[primary_id] = primary_inner

    primary_perspective = (
        f"{primary_p.name} 주도 발화 "
        f"(패턴: {routing.pattern.value}, 내면: {primary_inner.my_agenda})"
    )
    primary_system_prompt = reg.render_system_prompt(
        persona_id=primary_id,
        master_state=subconscious.master_state,
        context_summary=subconscious.context_summary,
        prev_vibe=prev_vibe_primary,
        perspective_context=primary_perspective,
    )

    llm_messages: list[BaseMessage] = list(state.get("messages", []))
    if not llm_messages or not isinstance(llm_messages[-1], HumanMessage):
        llm_messages.append(HumanMessage(content=user_query))

    try:
        router_res: Any = await router.route_and_generate(
            messages=llm_messages,
            system_prompt=primary_system_prompt,
        )
        if isinstance(router_res, str):
            primary_content = router_res
        elif hasattr(router_res, "content"):
            primary_content = str(router_res.content)
        else:
            primary_content = str(router_res)
    except Exception as exc:
        logger.error(
            "Router primary generation failed for speaker '%s': %s",
            primary_id,
            exc,
            exc_info=True,
        )
        raise

    is_slm = (
        primary_content.startswith(getattr(router, "auxiliary_prefix", "[Tactical Uplink"))
        or "[Auxiliary" in primary_content
        or "slm" in str(getattr(router_res, "model_name", "")).lower()
    )
    executed_engine = "slm" if is_slm else getattr(router_res, "engine", "gemini")
    executed_model = getattr(router_res, "model_name", "llamacpp" if is_slm else "gemini-3.7-flash")

    try:
        await adispatch_custom_event(
            "token",
            {
                "delta": primary_content,
                "content": primary_content,
                "speaker": primary_id,
                "avatar": getattr(primary_p, "avatar", None),
            },
        )
    except Exception:
        pass

    all_recipients = [p.id for p in active_personas if p.id != primary_id]
    primary_group_msg = GroupChatMessage(
        session_id=session_id,
        sender_id=primary_id,
        recipients=all_recipients,
        content=primary_content,
        inner_state_snapshot=primary_inner,
    )
    group_messages.append(primary_group_msg)
    out_messages.append(AIMessage(content=primary_content, name=primary_id))
    response_texts.append(f"{primary_p.name}: {primary_content}")

    # 2. Secondary Speaker Generation (if multi-speaker pattern)
    secondary_id = routing.secondary_speaker_id
    if secondary_id and secondary_id in persona_map:
        secondary_p = persona_map[secondary_id]
        prev_vibe_secondary = (
            persona_states[secondary_id].my_vibe if secondary_id in persona_states else None
        )

        secondary_inner = _synthesize_inner_state(
            persona=secondary_p,
            routing=routing,
            subconscious=subconscious,
            prev_vibe=prev_vibe_secondary,
            persona_id=secondary_id,
            user_query=user_query,
            is_secondary=True,
            primary_response=primary_content,
        )
        persona_states[secondary_id] = secondary_inner

        sec_perspective = (
            f"{primary_p.name}의 발화에 이은 {secondary_p.name} 연계 발화 "
            f"(패턴: {routing.pattern.value}, 내면: {secondary_inner.my_agenda})"
        )
        sec_system_prompt = reg.render_system_prompt(
            persona_id=secondary_id,
            master_state=subconscious.master_state,
            context_summary=subconscious.context_summary,
            prev_vibe=prev_vibe_secondary,
            perspective_context=sec_perspective,
        )

        sec_llm_messages: list[BaseMessage] = list(state.get("messages", []))
        if not sec_llm_messages or not isinstance(sec_llm_messages[-1], HumanMessage):
            sec_llm_messages.append(HumanMessage(content=user_query))
        sec_llm_messages.append(AIMessage(content=primary_content, name=primary_id))

        try:
            sec_router_res: Any = await router.route_and_generate(
                messages=sec_llm_messages,
                system_prompt=sec_system_prompt,
            )
            if isinstance(sec_router_res, str):
                secondary_content = sec_router_res
            elif hasattr(sec_router_res, "content"):
                secondary_content = str(sec_router_res.content)
            else:
                secondary_content = str(sec_router_res)
        except Exception as exc:
            logger.error(
                "Router secondary generation failed for speaker '%s': %s",
                secondary_id,
                exc,
                exc_info=True,
            )
            raise

        sec_is_slm = (
            secondary_content.startswith(getattr(router, "auxiliary_prefix", "[Tactical Uplink"))
            or "[Auxiliary" in secondary_content
            or "slm" in str(getattr(sec_router_res, "model_name", "")).lower()
        )
        if sec_is_slm:
            executed_engine = "slm"
            executed_model = getattr(sec_router_res, "model_name", "llamacpp")
        else:
            executed_engine = getattr(sec_router_res, "engine", executed_engine)
            executed_model = getattr(sec_router_res, "model_name", executed_model)

        try:
            await adispatch_custom_event(
                "token",
                {
                    "delta": secondary_content,
                    "content": secondary_content,
                    "speaker": secondary_id,
                    "avatar": getattr(secondary_p, "avatar", None),
                },
            )
        except Exception:
            pass

        secondary_group_msg = GroupChatMessage(
            session_id=session_id,
            sender_id=secondary_id,
            recipients=[p.id for p in active_personas if p.id != secondary_id],
            content=secondary_content,
            inner_state_snapshot=secondary_inner,
            reply_to_id=primary_group_msg.id,
        )
        group_messages.append(secondary_group_msg)
        out_messages.append(AIMessage(content=secondary_content, name=secondary_id))
        response_texts.append(f"{secondary_p.name}: {secondary_content}")

    combined_response = "\n\n".join(response_texts)

    return {
        "messages": out_messages,
        "final_response": combined_response,
        "persona_states": persona_states,
        "group_messages": group_messages,
        "engine": executed_engine,
        "model_name": executed_model,
    }


async def companion_postprocess_node(
    state: CompanionState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Persist session state and completed companion turn."""
    engine = state.get("engine") or "gemini"
    model_name = state.get("model_name") or "gemini-3.7-flash"
    return {
        "engine": engine,
        "model_name": model_name,
    }


# ---------------------------------------------------------------------------
# StateGraph Assembly
# ---------------------------------------------------------------------------


def build_companion_graph(
    router: HybridLLMRouter | None = None,
    slicer: DynamicSlicerEngine | None = None,
    registry: PersonaRegistry | None = None,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> StateGraph[Any, Any, Any, Any]:
    """Construct the LangGraph StateGraph for Cognitive Companion Engine.

    Execution Flow:
        START -> session_node -> slicer_node -> unified_cognitive_node -> companion_dispatch_node -> postprocess_node -> END

    Args:
        router: Optional HybridLLMRouter for model dispatch.
        slicer: Optional DynamicSlicerEngine for knowledge slicing.
        registry: Optional PersonaRegistry for persona management.
        session_manager: Optional SmartSessionManager.
        db_session: Optional AsyncSession for database operations.
        storage_manager: Optional FileStorageManager.
        background_tasks: Optional BackgroundTasks.

    Returns:
        Configured uncompiled StateGraph builder instance.
    """
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(CompanionState)

    reg = registry or get_default_registry()

    async def _bound_session(state: CompanionState) -> dict[str, Any]:
        return await companion_session_node(state=state, registry=reg)

    async def _bound_slicer(state: CompanionState) -> dict[str, Any]:
        return await companion_slicer_node(state=state, slicer=slicer)

    async def _bound_cognitive(state: CompanionState) -> dict[str, Any]:
        return await unified_cognitive_node(state=state, registry=reg)

    async def _bound_dispatch(state: CompanionState) -> dict[str, Any]:
        return await companion_dispatch_node(state=state, registry=reg, router=router)

    async def _bound_postprocess(state: CompanionState) -> dict[str, Any]:
        return await companion_postprocess_node(
            state=state,
            session_manager=session_manager,
            db_session=db_session,
            storage_manager=storage_manager,
            background_tasks=background_tasks,
        )

    # Add all 5 pipeline nodes
    builder.add_node("session_node", _bound_session)
    builder.add_node("slicer_node", _bound_slicer)
    builder.add_node("unified_cognitive_node", _bound_cognitive)
    builder.add_node("companion_dispatch_node", _bound_dispatch)
    builder.add_node("postprocess_node", _bound_postprocess)

    # Linear pipeline edges
    builder.add_edge(START, "session_node")
    builder.add_edge("session_node", "slicer_node")
    builder.add_edge("slicer_node", "unified_cognitive_node")
    builder.add_edge("unified_cognitive_node", "companion_dispatch_node")
    builder.add_edge("companion_dispatch_node", "postprocess_node")
    builder.add_edge("postprocess_node", END)

    return builder


def compile_companion_graph(
    builder: StateGraph[Any, Any, Any, Any],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the companion StateGraph into a runnable graph."""
    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


def create_companion_graph(
    router: HybridLLMRouter | None = None,
    slicer: DynamicSlicerEngine | None = None,
    registry: PersonaRegistry | None = None,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Convenience factory to build and compile the companion StateGraph."""
    builder = build_companion_graph(
        router=router,
        slicer=slicer,
        registry=registry,
        session_manager=session_manager,
        db_session=db_session,
        storage_manager=storage_manager,
    )
    return compile_companion_graph(builder=builder, checkpointer=checkpointer)


__all__ = [
    "CompanionState",
    "_synthesize_inner_state",
    "build_companion_graph",
    "companion_dispatch_node",
    "companion_postprocess_node",
    "companion_session_node",
    "companion_slicer_node",
    "compile_companion_graph",
    "create_companion_graph",
]
