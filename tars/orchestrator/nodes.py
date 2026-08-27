"""StateGraph node definitions for the TARS orchestration pipeline.

Defines:
- slicer_node: Dynamic knowledge retrieval via DynamicSlicerEngine
- prompt_node: System prompt construction with persona and OKF XML context
- llm_node: Response generation with tool call detection
- tool_node: Exception-isolated tool execution with graceful TARS fallback
- should_continue: Conditional routing function for ReAct loop
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.config import get_settings
from tars.core.okf.models import OKFDocument
from tars.orchestrator.state import (
    DEFAULT_HONESTY_LEVEL,
    DEFAULT_HUMOR_LEVEL,
    DEFAULT_MODE,
    TARSState,
)
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.orchestrator.nodes")


def _extract_active_query(messages: Sequence[BaseMessage]) -> str:
    """Extract the most recent human query string from the message history."""
    if not messages:
        return ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if getattr(msg, "type", "") == "human":
            return str(msg.content)

    # Fallback to the last message content if no HumanMessage explicit type found
    last_msg = messages[-1]
    return str(getattr(last_msg, "content", ""))


async def slicer_node(
    state: TARSState,
    slicer: DynamicSlicerEngine | None = None,
) -> dict[str, Any]:
    """Execute dynamic knowledge slicing on the user's stored OKF wikis.

    Args:
        state: Current graph state containing messages and user_id.
        slicer: Optional injected DynamicSlicerEngine instance.

    Returns:
        Dictionary update with key 'relevant_wikis'.
    """
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])
    query = _extract_active_query(messages)

    if not user_id or slicer is None:
        logger.debug("slicer_node skipped: user_id=%s, slicer=%s", user_id, slicer is not None)
        return {"relevant_wikis": []}

    try:
        relevant_wikis: list[OKFDocument] = await slicer.slice_context(
            user_id=user_id,
            query=query,
            token_budget=1500,
        )
        return {"relevant_wikis": relevant_wikis}
    except Exception as exc:
        logger.error("Error during dynamic slicing for user %s: %s", user_id, exc, exc_info=True)
        return {"relevant_wikis": []}


async def prompt_node(
    state: TARSState,
    persona_manager: TARSPersonaManager | None = None,
) -> dict[str, Any]:
    """Compose the full TARS system prompt with persona parameters and OKF XML context.

    Args:
        state: Current graph state containing persona parameters and relevant_wikis.
        persona_manager: Optional injected TARSPersonaManager instance.

    Returns:
        Dictionary update with key 'system_prompt'.
    """
    manager = persona_manager or TARSPersonaManager()

    humor_level = float(state.get("humor_level", DEFAULT_HUMOR_LEVEL))
    honesty_level = float(state.get("honesty_level", DEFAULT_HONESTY_LEVEL))
    mode = str(state.get("mode", DEFAULT_MODE))
    relevant_wikis: list[OKFDocument] = state.get("relevant_wikis", [])

    system_prompt = manager.build_system_prompt(
        humor_level=humor_level,
        honesty_level=honesty_level,
        mode=mode,
        context_docs=relevant_wikis,
    )

    return {"system_prompt": system_prompt}


async def llm_node(
    state: TARSState,
    router: HybridLLMRouter | None = None,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Invoke the Hybrid LLM Router to generate response or request tool calls.

    Args:
        state: Current graph state containing messages and system_prompt.
        router: Configured HybridLLMRouter instance.
        tool_registry: Optional ToolRegistry containing available tools.

    Returns:
        Dictionary update with final_response, messages, and tool_calls.
    """
    if router is None:
        raise ValueError("HybridLLMRouter must be provided to llm_node.")

    messages = state.get("messages", [])
    system_prompt = state.get("system_prompt", "")

    # If tool registry is bound, use structured response generation
    if tool_registry is not None:
        tool_declarations = tool_registry.export_gemini_declarations()
        resp = await router.route_and_generate_response(
            messages=list(messages),
            system_prompt=system_prompt,
            tools=tool_declarations,
        )

        if resp.tool_calls:
            langchain_tool_calls = [
                {"id": tc.id, "name": tc.name, "args": tc.arguments} for tc in resp.tool_calls
            ]
            ai_msg = AIMessage(content=resp.content, tool_calls=langchain_tool_calls)
            return {
                "final_response": resp.content,
                "messages": [ai_msg],
                "tool_calls": resp.tool_calls,
            }

        ai_msg = AIMessage(content=resp.content)
        return {
            "final_response": resp.content,
            "messages": [ai_msg],
            "tool_calls": [],
        }

    # Standard text streaming for casual chat or non-tool generation
    chunks: list[str] = []
    async for chunk in router.route_and_stream(
        messages=list(messages),
        system_prompt=system_prompt,
    ):
        chunks.append(chunk)

    final_text = "".join(chunks)
    ai_message = AIMessage(content=final_text)

    return {
        "final_response": final_text,
        "messages": [ai_message],
        "tool_calls": [],
    }


async def tool_node(
    state: TARSState,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Execute pending tool calls with exception isolation and graceful TARS fallback.

    Args:
        state: Current graph state containing tool_calls.
        tool_registry: ToolRegistry instance to execute tools from.

    Returns:
        Dictionary update with tool execution results and ToolMessages.
    """
    pending_tool_calls: list[ToolCallData] = list(state.get("tool_calls", []))

    # Check if latest message in state is an AIMessage with tool_calls
    if not pending_tool_calls and state.get("messages"):
        last_msg = state["messages"][-1]
        msg_tool_calls = getattr(last_msg, "tool_calls", [])
        if msg_tool_calls:
            for tc in msg_tool_calls:
                if isinstance(tc, dict):
                    pending_tool_calls.append(
                        ToolCallData(
                            id=str(tc.get("id", "call_default")),
                            name=str(tc.get("name", "")),
                            arguments=dict(tc.get("args", {})),
                        )
                    )

    if not pending_tool_calls:
        return {}

    tool_messages: list[BaseMessage] = []
    results: list[dict[str, Any]] = []
    last_error: str | None = None

    for tc in pending_tool_calls:
        try:
            if tool_registry is None:
                raise RuntimeError("ToolRegistry is not configured in tool_node.")

            exec_result = await tool_registry.execute_tool(tc.name, tc.arguments)
            content_str = (
                json.dumps(exec_result, ensure_ascii=False)
                if not isinstance(exec_result, str)
                else exec_result
            )
            tool_messages.append(ToolMessage(content=content_str, tool_call_id=tc.id, name=tc.name))
            results.append({"tool": tc.name, "status": "success", "result": exec_result})
        except Exception as exc:
            err_detail = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Tool '%s' execution failed: %s. Engaging graceful fallback.",
                tc.name,
                err_detail,
            )
            fallback_payload = {
                "status": "error",
                "tool": tc.name,
                "error_detail": err_detail,
                "directive": "Acknowledge tool failure dryly in TARS deadpan persona and suggest alternative.",
            }
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(fallback_payload, ensure_ascii=False),
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
            results.append({"tool": tc.name, "status": "error", "error": err_detail})
            last_error = err_detail

    current_iterations = int(state.get("iteration_count", 0))
    all_results = list(state.get("tool_results", [])) + results
    return {
        "messages": tool_messages,
        "tool_calls": [],
        "tool_results": all_results,
        "iteration_count": current_iterations + 1,
        "error_message": last_error,
    }


def should_continue(state: TARSState) -> str:
    """Determine whether to route to tool_node for tool execution or finish at END.

    Args:
        state: Current graph state.

    Returns:
        'tool_node' if pending tool calls remain within iteration budget, else END.
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

    return END


__all__ = [
    "llm_node",
    "prompt_node",
    "should_continue",
    "slicer_node",
    "tool_node",
]
