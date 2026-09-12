"""Conditional routing functions for TARS orchestration pipeline."""

from __future__ import annotations

import logging

from tars.config import get_settings
from tars.engine.orchestrator.state import TARSState

logger = logging.getLogger("tars.engine.orchestrator.nodes.routing")


def should_continue(state: TARSState) -> str:
    """Determine whether to route to tool_node for tool execution or finish.

    Args:
        state: Current graph state.

    Returns:
        'tool_node' if pending tool calls remain within iteration budget, else 'postprocess_node'.
    """
    tool_calls = state.get("tool_calls", [])
    if not tool_calls and state.get("messages"):
        last_msg = state["messages"][-1]
        msg_tool_calls = getattr(last_msg, "tool_calls", [])
        if msg_tool_calls:
            tool_calls = msg_tool_calls

    iteration_count = int(state.get("iteration_count", 0))
    max_iterations = int(get_settings().max_tool_iterations)

    if tool_calls and len(tool_calls) > 0 and iteration_count < max_iterations:
        return "tool_node"

    return "postprocess_node"
