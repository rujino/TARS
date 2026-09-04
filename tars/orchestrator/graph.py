"""LangGraph StateGraph construction, compilation, and execution for TARS.

Provides:
- build_tars_graph: Builds StateGraph with session routing, reset handling, ReAct loop, and postprocessing.
- compile_tars_graph: Compiles StateGraph with optional checkpointing.
- create_tars_graph: Factory convenience function.
- check_reset: Conditional edge routing function for session reset detection.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.router import HybridLLMRouter
from tars.core.session.manager import SmartSessionManager
from tars.orchestrator.nodes import (
    llm_node,
    postprocess_node,
    prompt_node,
    reset_node,
    session_node,
    should_continue,
    slicer_node,
    tool_node,
)
from tars.orchestrator.state import TARSState
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.orchestrator.graph")


def check_reset(state: TARSState) -> str:
    """Determine whether state indicates a natural reset command.

    Args:
        state: Current graph state evaluated by session_node.

    Returns:
        'reset_node' if is_reset is True, else 'slicer_node'.
    """
    if state.get("is_reset", False):
        return "reset_node"
    return "slicer_node"


def build_tars_graph(
    router: HybridLLMRouter,
    slicer: DynamicSlicerEngine,
    persona_manager: TARSPersonaManager | None = None,
    tool_registry: ToolRegistry | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    session_manager: SmartSessionManager | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> StateGraph[Any, Any, Any, Any]:
    """Construct and configure the LangGraph StateGraph nodes and routing edges.

    Execution Flow:
        START -> session_node -> [check_reset?]
                                      ├── (Yes: is_reset) ──> reset_node ────────────────────────┐
                                      │                                                          │
                                      └── (No: normal)    ──> slicer_node -> prompt_node -> llm_node -> [should_continue?]
                                                                                                ▲             │ (tool_calls)
                                                                                                │             ▼
                                                                                                └── tool_node ◄
                                                                                                              │ (no tools / max iter)
                                                                                                              ▼
                                                                                                      postprocess_node
                                                                                                              │
                                                                                                              ▼
                                                                                                             END

    Args:
        router: Configured HybridLLMRouter for routing and generation.
        slicer: Configured DynamicSlicerEngine for context retrieval.
        persona_manager: Optional persona manager for prompt construction.
        tool_registry: Optional ToolRegistry containing registered tools.
        db_session: Optional SQLAlchemy AsyncSession for DB operations.
        storage_manager: Optional FileStorageManager instance.
        session_manager: Optional SmartSessionManager instance.
        background_tasks: Optional FastAPI BackgroundTasks for async tasks.

    Returns:
        Configured uncompiled StateGraph builder instance.
    """
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(TARSState)

    # Wrap node executions with bound dependencies
    async def _bound_session_node(state: TARSState) -> dict[str, Any]:
        return await session_node(
            state=state,
            session_manager=session_manager,
            db_session=db_session,
            storage_manager=storage_manager,
            router=router,
            background_tasks=background_tasks,
        )

    async def _bound_reset_node(state: TARSState) -> dict[str, Any]:
        return await reset_node(state=state)

    async def _bound_slicer_node(state: TARSState) -> dict[str, Any]:
        return await slicer_node(state=state, slicer=slicer)

    async def _bound_prompt_node(state: TARSState) -> dict[str, Any]:
        return await prompt_node(state=state, persona_manager=persona_manager)

    async def _bound_llm_node(state: TARSState) -> dict[str, Any]:
        return await llm_node(state=state, router=router, tool_registry=tool_registry)

    async def _bound_tool_node(state: TARSState) -> dict[str, Any]:
        return await tool_node(state=state, tool_registry=tool_registry)

    async def _bound_postprocess_node(state: TARSState) -> dict[str, Any]:
        return await postprocess_node(
            state=state,
            session_manager=session_manager,
            db_session=db_session,
            storage_manager=storage_manager,
            router=router,
            background_tasks=background_tasks,
        )

    # Register all 7 nodes
    builder.add_node("session_node", _bound_session_node)
    builder.add_node("reset_node", _bound_reset_node)
    builder.add_node("slicer_node", _bound_slicer_node)
    builder.add_node("prompt_node", _bound_prompt_node)
    builder.add_node("llm_node", _bound_llm_node)
    builder.add_node("tool_node", _bound_tool_node)
    builder.add_node("postprocess_node", _bound_postprocess_node)

    # Entry point
    builder.add_edge(START, "session_node")

    # 1. Reset conditional routing
    builder.add_conditional_edges(
        "session_node",
        check_reset,
        {
            "reset_node": "reset_node",
            "slicer_node": "slicer_node",
        },
    )

    # 2. Reset complete -> postprocessing
    builder.add_edge("reset_node", "postprocess_node")

    # 3. Regular dialogue pipeline
    builder.add_edge("slicer_node", "prompt_node")
    builder.add_edge("prompt_node", "llm_node")

    # 4. ReAct loop conditional branch
    builder.add_conditional_edges(
        "llm_node",
        should_continue,
        {
            "tool_node": "tool_node",
            "postprocess_node": "postprocess_node",
        },
    )
    builder.add_edge("tool_node", "llm_node")

    # 5. Postprocess complete -> END
    builder.add_edge("postprocess_node", END)

    return builder


def compile_tars_graph(
    builder: StateGraph[Any, Any, Any, Any],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the configured StateGraph into a runnable state machine.

    Args:
        builder: Uncompiled StateGraph instance from build_tars_graph.
        checkpointer: Optional persistence checkpointer for multi-turn session state.

    Returns:
        CompiledStateGraph instance ready for ainvoke and astream.
    """
    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


def create_tars_graph(
    router: HybridLLMRouter,
    slicer: DynamicSlicerEngine,
    persona_manager: TARSPersonaManager | None = None,
    tool_registry: ToolRegistry | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    session_manager: SmartSessionManager | None = None,
    background_tasks: BackgroundTasks | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """One-shot factory to build and compile the complete TARS StateGraph pipeline.

    Args:
        router: Configured HybridLLMRouter.
        slicer: Configured DynamicSlicerEngine.
        persona_manager: Optional TARSPersonaManager.
        tool_registry: Optional ToolRegistry.
        db_session: Optional AsyncSession.
        storage_manager: Optional FileStorageManager.
        session_manager: Optional SmartSessionManager.
        background_tasks: Optional BackgroundTasks.
        checkpointer: Optional BaseCheckpointSaver for state persistence.

    Returns:
        CompiledStateGraph instance.
    """
    builder = build_tars_graph(
        router=router,
        slicer=slicer,
        persona_manager=persona_manager,
        tool_registry=tool_registry,
        db_session=db_session,
        storage_manager=storage_manager,
        session_manager=session_manager,
        background_tasks=background_tasks,
    )
    return compile_tars_graph(builder=builder, checkpointer=checkpointer)


__all__ = [
    "build_tars_graph",
    "check_reset",
    "compile_tars_graph",
    "create_tars_graph",
]
