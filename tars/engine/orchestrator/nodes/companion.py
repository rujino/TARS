"""Companion pipeline execution nodes for TARS Cognitive Companion Engine.

Provides modular node implementations for:
- companion_session_node: Resolves active personas and hydrates working memory.
- companion_slicer_node: Dynamic knowledge retrieval for companion context.
- companion_dispatch_node: Pluggable multi-companion LLM response generation.
- companion_postprocess_node: Post-execution turn state persistence.
- _synthesize_inner_state: Autonomous inner state synthesis delegating to PersonaDefinition.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

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
from tars.engine.orchestrator.nodes.session import _extract_active_query

if TYPE_CHECKING:
    from fastapi import BackgroundTasks
    from sqlalchemy.ext.asyncio import AsyncSession

    from tars.core.session.manager import SmartSessionManager
    from tars.domains.knowledge.slicer.engine import DynamicSlicerEngine
    from tars.domains.knowledge.storage.manager import FileStorageManager
    from tars.engine.adapters.router import HybridLLMRouter
    from tars.engine.orchestrator.graphs.companion import CompanionState

logger = logging.getLogger("tars.engine.orchestrator.nodes.companion")


async def companion_session_node(
    state: CompanionState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
    registry: PersonaRegistry | None = None,
) -> dict[str, Any]:
    """Initialize session: In-Memory Hot Path if ongoing, Cold Start DB Hydration if empty."""
    user_id = state.get("user_id", "")
    session_id = state.get("session_id")
    messages = list(state.get("messages", []))
    explicit_query = state.get("active_query", "")
    active_query = explicit_query if explicit_query else _extract_active_query(messages)

    force_new = bool(state.get("force_new", False))
    client_tz = state.get("client_timezone") or "Asia/Seoul"

    # 1. Hot Path vs Cold Start 판별:
    # 이미 2개 이상의 턴(이전 문답)이 인메모리 messages에 누적되어 있다면 대화 진행 중(Hot Path)임.
    # 단, 사용자가 명시적으로 '새 대화'를 요청한 경우(force_new=True)에는 Hot Path를 무시하고 신규 세션을 라우팅함.
    is_hot_path = (
        not force_new
        and len(messages) > 1
        and any(isinstance(m, AIMessage) for m in messages)
    )

    if is_hot_path:
        active_session_id = session_id or "default_session"
        hydrated_messages = messages
        if not isinstance(hydrated_messages[-1], HumanMessage):
            hydrated_messages.append(HumanMessage(content=active_query))
    else:
        # Cold Start 또는 새 대화 요청(force_new): DB 세션 라우팅 1회 실행
        session_mgr = session_manager
        if session_mgr is None and db_session is not None:
            from tars.core.session.manager import SmartSessionManager
            from tars.domains.knowledge.storage.manager import FileStorageManager

            session_mgr = SmartSessionManager(
                db_session=db_session,
                storage_manager=storage_manager or FileStorageManager(),
                llm_adapter=router,
            )

        if session_mgr is not None and user_id:
            active_session, working_memory, _ = await session_mgr.route_session(
                user_id=user_id,
                requested_session_id=None if force_new else session_id,
                incoming_message=active_query,
                background_tasks=background_tasks,
                force_new=force_new,
                client_timezone=client_tz,
            )
            active_session_id = active_session.id
            hydrated_messages = list(working_memory) + [HumanMessage(content=active_query)]
        else:
            active_session_id = session_id or "default_session"
            hydrated_messages = [HumanMessage(content=active_query)] if force_new else (list(messages) if messages else [HumanMessage(content=active_query)])

    # 2. 페르소나 레지스트리 해소
    reg = registry or get_default_registry()
    active_ids = state.get("active_persona_ids")
    if active_ids:
        valid_personas = [reg.get(pid) for pid in active_ids if reg.has(pid)]
        active_personas = valid_personas if valid_personas else reg.list_all()
    else:
        active_personas = reg.list_all()
    active_ids = [p.id for p in active_personas]

    persona_states = dict(state.get("persona_states") or {})

    return {
        "session_id": active_session_id,
        "active_query": active_query,
        "messages": hydrated_messages,
        "active_persona_ids": active_ids,
        "active_personas": active_personas,
        "persona_states": persona_states,
    }


async def companion_slicer_node(
    state: CompanionState,
    slicer: DynamicSlicerEngine | None = None,
) -> dict[str, Any]:
    """Slice relevant OKF context and thought nodes for companion context."""
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
    registry: PersonaRegistry | None = None,
    **kwargs: Any,
) -> CharacterInnerState:
    """Synthesize autonomous CharacterInnerState (my_vibe and my_agenda) purely from state.

    Delegates autonomous inner agency to pluggable PersonaDefinition metadata,
    adhering to the Open-Closed Principle (OCP).
    """
    # 1. Resolve speaker persona identifier
    target_id: str
    if persona_id:
        target_id = persona_id
    elif persona is not None:
        target_id = persona.id if isinstance(persona, PersonaDefinition) else str(persona)
    elif routing is not None:
        target_id = (
            routing.secondary_speaker_id
            if (is_secondary and routing.secondary_speaker_id)
            else routing.primary_speaker_id
        )
    else:
        target_id = "default"

    # 2. Resolve routing pattern & metadata
    pattern = routing.pattern if routing is not None else RoutingPattern.SOLO
    dialogue_tone = getattr(routing, "dialogue_tone", None) if routing else None
    turn_intent = getattr(routing, "turn_intent", None) if routing else None

    # 3. Delegate to PersonaDefinition instance or PersonaRegistry
    reg = registry or get_default_registry()
    if isinstance(persona, PersonaDefinition):
        return persona.synthesize_inner_state(
            pattern=pattern,
            prev_vibe=prev_vibe,
            dialogue_tone=dialogue_tone,
            turn_intent=turn_intent,
        )

    return reg.synthesize_inner_state(
        persona_id=target_id,
        pattern=pattern,
        prev_vibe=prev_vibe,
        dialogue_tone=dialogue_tone,
        turn_intent=turn_intent,
    )


async def companion_dispatch_node(
    state: CompanionState,
    registry: PersonaRegistry | None = None,
    router: HybridLLMRouter | None = None,
) -> dict[str, Any]:
    """
    Execute Tier 2 conscious companion dispatching and genuine LLM generation.
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
        fallback_speaker_id = active_personas[0].id if active_personas else "companion"
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
        registry=reg,
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
    out_messages.append(AIMessage(content=f"[{primary_p.name}]: {primary_content}", name=primary_id))
    response_texts.append(f"[{primary_p.name}]: {primary_content}")

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
            registry=reg,
        )
        persona_states[secondary_id] = secondary_inner

        sec_perspective = (
            f"{primary_p.name}의 발화('[ {primary_p.name}]: {primary_content}')에 이은 {secondary_p.name} 연계 발화 "
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
        sec_llm_messages.append(
            AIMessage(content=f"[{primary_p.name}]: {primary_content}", name=primary_id)
        )

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
        out_messages.append(
            AIMessage(content=f"[{secondary_p.name}]: {secondary_content}", name=secondary_id)
        )
        response_texts.append(f"[{secondary_p.name}]: {secondary_content}")

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
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Persist completed multi-companion turn into DB as single combined assistant turn."""
    user_id = state.get("user_id", "")
    session_id = state.get("session_id", "")
    active_query = state.get("active_query", "")
    final_response = state.get("final_response", "")
    engine = state.get("engine") or "gemini"
    model_name = state.get("model_name") or "gemini-3.7-flash"

    session_mgr = session_manager
    if session_mgr is None and db_session is not None:
        from tars.core.session.manager import SmartSessionManager
        from tars.domains.knowledge.storage.manager import FileStorageManager

        session_mgr = SmartSessionManager(
            db_session=db_session,
            storage_manager=storage_manager or FileStorageManager(),
            llm_adapter=router,
        )

    # 1. DB 턴 영속화 (Write-Only): User 발화 + 복합 컴패니언 응답 단일 assistant 레코드
    if session_mgr is not None and user_id and session_id and active_query and final_response:
        try:
            await session_mgr.record_turn(
                session_id=session_id,
                user_id=user_id,
                user_content=active_query,
                assistant_content=final_response,
            )
        except Exception as exc:
            logger.error("Failed to record multi-companion turn in DB: %s", exc, exc_info=True)

    # 2. 백그라운드 지식 추출 스케줄링
    if user_id and active_query and final_response and storage_manager is not None:
        turns: list[BaseMessage] = [
            HumanMessage(content=active_query),
            AIMessage(content=final_response),
        ]
        from tars.domains.chat.services.agent_chat import execute_background_knowledge_extraction

        if background_tasks is not None:
            background_tasks.add_task(
                execute_background_knowledge_extraction,
                user_id=user_id,
                conversation_turns=turns,
                storage=storage_manager,
                llm_adapter=router,
            )
        else:
            try:
                import asyncio
                from tars.engine.orchestrator.nodes.postprocess import _background_node_tasks

                task = asyncio.create_task(
                    execute_background_knowledge_extraction(
                        user_id=user_id,
                        conversation_turns=turns,
                        storage=storage_manager,
                        llm_adapter=router,
                    )
                )
                _background_node_tasks.add(task)
                task.add_done_callback(_background_node_tasks.discard)
            except Exception as bg_err:
                logger.error(
                    "Failed to dispatch background knowledge extraction in companion_postprocess_node: %s",
                    bg_err,
                    exc_info=True,
                )

    return {
        "engine": engine,
        "model_name": model_name,
    }


__all__ = [
    "_synthesize_inner_state",
    "companion_dispatch_node",
    "companion_postprocess_node",
    "companion_session_node",
    "companion_slicer_node",
]
