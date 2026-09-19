"""StateGraph node definitions for the TARS orchestration pipeline.

Exports individual pipeline nodes, conditional routing edges, and background lifecycle handlers.
"""

from tars.engine.orchestrator.nodes.cognitive import (
    evaluate_tom_prediction_feedback,
    extract_master_state_and_desire,
    unified_cognitive_node,
)
from tars.engine.orchestrator.nodes.companion import (
    _synthesize_inner_state,
    companion_dispatch_node,
    companion_postprocess_node,
    companion_session_node,
    companion_slicer_node,
)
from tars.engine.orchestrator.nodes.llm import llm_node
from tars.engine.orchestrator.nodes.postprocess import (
    _background_node_tasks,
    postprocess_node,
    shutdown_background_tasks,
)
from tars.engine.orchestrator.nodes.prompt import prompt_node
from tars.engine.orchestrator.nodes.routing import should_continue
from tars.engine.orchestrator.nodes.session import (
    _extract_active_query,
    reset_node,
    session_node,
)
from tars.engine.orchestrator.nodes.slicer import slicer_node
from tars.engine.orchestrator.nodes.tool import tool_node

__all__ = [
    "_background_node_tasks",
    "_extract_active_query",
    "_synthesize_inner_state",
    "companion_dispatch_node",
    "companion_postprocess_node",
    "companion_session_node",
    "companion_slicer_node",
    "evaluate_tom_prediction_feedback",
    "extract_master_state_and_desire",
    "llm_node",
    "postprocess_node",
    "prompt_node",
    "reset_node",
    "session_node",
    "should_continue",
    "shutdown_background_tasks",
    "slicer_node",
    "tool_node",
    "unified_cognitive_node",
]
