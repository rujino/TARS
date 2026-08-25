"""LangGraph StateGraph construction, compilation, and streaming execution for TARS.

Provides build_tars_graph, compile_tars_graph, and create_tars_graph.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from tars.adapters.router import HybridLLMRouter
from tars.orchestrator.nodes import llm_node, prompt_node, slicer_node
from tars.orchestrator.state import TARSState
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine

logger = logging.getLogger("tars.orchestrator.graph")


def build_tars_graph(
    router: HybridLLMRouter,
    slicer: DynamicSlicerEngine,
    persona_manager: TARSPersonaManager | None = None,
) -> StateGraph[Any, Any, Any, Any]:
    """Construct and configure the LangGraph StateGraph nodes and linear edges.

    Execution Flow:
        START -> slicer_node -> prompt_node -> llm_node -> END

    Args:
        router: Configured HybridLLMRouter for routing and generation.
        slicer: Configured DynamicSlicerEngine for context retrieval.
        persona_manager: Optional persona manager for prompt construction.

    Returns:
        Configured uncompiled StateGraph builder instance.
    """
    builder: StateGraph[Any, Any, Any, Any] = StateGraph(TARSState)

    # Wrap node executions with bound dependencies
    async def _bound_slicer_node(state: TARSState) -> dict[str, Any]:
        return await slicer_node(state=state, slicer=slicer)

    async def _bound_prompt_node(state: TARSState) -> dict[str, Any]:
        return await prompt_node(state=state, persona_manager=persona_manager)

    async def _bound_llm_node(state: TARSState) -> dict[str, Any]:
        return await llm_node(state=state, router=router)

    # Register nodes
    builder.add_node("slicer_node", _bound_slicer_node)
    builder.add_node("prompt_node", _bound_prompt_node)
    builder.add_node("llm_node", _bound_llm_node)

    # Register edges
    builder.add_edge(START, "slicer_node")
    builder.add_edge("slicer_node", "prompt_node")
    builder.add_edge("prompt_node", "llm_node")
    builder.add_edge("llm_node", END)

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
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """One-shot factory to build and compile the complete TARS StateGraph pipeline.

    Args:
        router: Configured HybridLLMRouter.
        slicer: Configured DynamicSlicerEngine.
        persona_manager: Optional TARSPersonaManager.
        checkpointer: Optional BaseCheckpointSaver for state persistence.

    Returns:
        CompiledStateGraph instance.
    """
    builder = build_tars_graph(
        router=router,
        slicer=slicer,
        persona_manager=persona_manager,
    )
    return compile_tars_graph(builder=builder, checkpointer=checkpointer)


__all__ = [
    "build_tars_graph",
    "compile_tars_graph",
    "create_tars_graph",
]
