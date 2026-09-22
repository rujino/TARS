"""LangGraph Companion Pipeline for TARS Cognitive Companion Engine.

Assembles the 2-tier cognitive companion architecture:
START -> session_node -> slicer_node -> unified_cognitive_node -> companion_dispatch_node -> postprocess_node -> END

Supports both 1:1 solo sessions and dynamic multi-companion group chats
with pluggable turn arbitration, Theory of Mind, and perspective projection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from tars.domains.knowledge.spec.schemas import OKFDocument
from tars.domains.persona.registry import PersonaRegistry, get_default_registry
from tars.domains.persona.schemas import (
    CharacterInnerState,
    GroupChatMessage,
    PersonaDefinition,
    SubconsciousStatePayload,
    TurnRoutingDecision,
)
from tars.engine.adapters.router import HybridLLMRouter
from tars.engine.orchestrator.nodes.cognitive import unified_cognitive_node
from tars.engine.orchestrator.nodes.companion import (
    _synthesize_inner_state,
    companion_dispatch_node,
    companion_postprocess_node,
    companion_session_node,
    companion_slicer_node,
)

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
    force_new: bool | None
    client_timezone: str | None


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
        registry: Optional PersonaRegistry for dynamic persona management.
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
        return await companion_session_node(
            state=state,
            session_manager=session_manager,
            db_session=db_session,
            storage_manager=storage_manager,
            router=router,
            background_tasks=background_tasks,
            registry=reg,
        )

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
            router=router,
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
    background_tasks: BackgroundTasks | None = None,
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
        background_tasks=background_tasks,
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
