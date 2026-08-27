"""LangGraph StateGraph construction, compilation, and streaming execution for TARS.

Provides:
- build_tars_graph: Builds StateGraph with ReAct loop and tool fallback
- compile_tars_graph: Compiles StateGraph with optional checkpointing
- create_tars_graph: Factory convenience function
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from tars.adapters.router import HybridLLMRouter
from tars.orchestrator.nodes import llm_node, prompt_node, should_continue, slicer_node, tool_node
from tars.orchestrator.state import TARSState
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.orchestrator.graph")


def build_tars_graph(
    router: HybridLLMRouter,
    slicer: DynamicSlicerEngine,
    persona_manager: TARSPersonaManager | None = None,
    tool_registry: ToolRegistry | None = None,
) -> StateGraph[Any, Any, Any, Any]:
    """Construct and configure the LangGraph StateGraph nodes and ReAct loop edges.

    Execution Flow:
        START -> slicer_node -> prompt_node -> llm_node -> [should_continue?]
                                                   ▲             │
                                                   │             ▼
                                                   └── tool_node ◄── (if has tool_calls)
                                                                 │
                                                                 ▼ (if no tools / max iter)
                                                                END

    Args:
        router: Configured HybridLLMRouter for routing and generation.
        slicer: Configured DynamicSlicerEngine for context retrieval.
        persona_manager: Optional persona manager for prompt construction.
        tool_registry: Optional ToolRegistry containing registered tools.

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
        return await llm_node(state=state, router=router, tool_registry=tool_registry)

    async def _bound_tool_node(state: TARSState) -> dict[str, Any]:
        return await tool_node(state=state, tool_registry=tool_registry)

    # Register nodes
    builder.add_node("slicer_node", _bound_slicer_node)
    builder.add_node("prompt_node", _bound_prompt_node)
    builder.add_node("llm_node", _bound_llm_node)
    builder.add_node("tool_node", _bound_tool_node)

    # Register linear and conditional edges
    builder.add_edge(START, "slicer_node")
    builder.add_edge("slicer_node", "prompt_node")
    builder.add_edge("prompt_node", "llm_node")

    # Conditional routing from llm_node to tool_node or END
    builder.add_conditional_edges(
        "llm_node",
        should_continue,
        {
            "tool_node": "tool_node",
            END: END,
        },
    )

    # ReAct cycle: tool_node outputs back into llm_node
    builder.add_edge("tool_node", "llm_node")

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
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """One-shot factory to build and compile the complete TARS StateGraph pipeline.

    Args:
        router: Configured HybridLLMRouter.
        slicer: Configured DynamicSlicerEngine.
        persona_manager: Optional TARSPersonaManager.
        tool_registry: Optional ToolRegistry.
        checkpointer: Optional BaseCheckpointSaver for state persistence.

    Returns:
        CompiledStateGraph instance.
    """
    builder = build_tars_graph(
        router=router,
        slicer=slicer,
        persona_manager=persona_manager,
        tool_registry=tool_registry,
    )
    return compile_tars_graph(builder=builder, checkpointer=checkpointer)


__all__ = [
    "build_tars_graph",
    "compile_tars_graph",
    "create_tars_graph",
]
