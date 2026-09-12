"""Tool execution node for TARS orchestration pipeline."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import BaseMessage, ToolMessage

from tars.engine.adapters.base import ToolCallData
from tars.engine.orchestrator.state import TARSState

if TYPE_CHECKING:
    from tars.domains.tools.registry import ToolRegistry

logger = logging.getLogger("tars.engine.orchestrator.nodes.tool")


async def tool_node(
    state: TARSState,
    tool_registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """Execute pending tool calls with exception isolation and graceful TARS fallback.

    Normalizes execution outcomes with standard delimiter boundaries to prevent
    untrusted tool outputs from acting as system commands.

    Args:
        state: Current graph state containing tool_calls and iteration_count.
        tool_registry: ToolRegistry instance to execute tools from.

    Returns:
        Dictionary update with tool execution results, ToolMessages, and tools_used.
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
    executed_tools: list[str] = []
    last_error: str | None = None
    disabled_tools = set(state.get("disabled_tools") or [])

    for tc in pending_tool_calls:
        try:
            await adispatch_custom_event(
                "tool_start",
                {"tool": tc.name, "call_id": tc.id, "args": tc.arguments},
            )
        except Exception:
            pass

        # Defense-in-depth guard: block execution if tool is disabled
        if tc.name in disabled_tools:
            err_detail = f"Tool '{tc.name}' is disabled by user configuration."
            logger.warning("Blocked execution of disabled tool '%s'.", tc.name)
            try:
                await adispatch_custom_event(
                    "tool_result",
                    {
                        "tool": tc.name,
                        "call_id": tc.id,
                        "status": "error",
                        "error": err_detail,
                    },
                )
            except Exception:
                pass
            content_str = f"[Tool Blocked: {tc.name}]\nError: {err_detail}"
            tool_messages.append(
                ToolMessage(
                    content=content_str,
                    tool_call_id=tc.id,
                    name=tc.name,
                )
            )
            results.append(
                {
                    "tool": tc.name,
                    "call_id": tc.id,
                    "args": tc.arguments,
                    "status": "error",
                    "error": err_detail,
                }
            )
            last_error = err_detail
            continue

        executed_tools.append(tc.name)

        try:
            if tool_registry is None:
                raise RuntimeError("ToolRegistry is not configured in tool_node.")

            user_id = state.get("user_id")
            exec_result = await tool_registry.execute_tool(tc.name, tc.arguments, user_id=user_id)
            try:
                await adispatch_custom_event(
                    "tool_result",
                    {
                        "tool": tc.name,
                        "call_id": tc.id,
                        "status": "success",
                        "result": exec_result,
                    },
                )
            except Exception:
                pass

            raw_content = (
                json.dumps(exec_result, ensure_ascii=False)
                if not isinstance(exec_result, str)
                else exec_result
            )
            # Enclose in standard boundary delimiter so LLM treats as untrusted execution data
            content_str = f"[Tool Result: {tc.name}]\n{raw_content}"
            tool_messages.append(ToolMessage(content=content_str, tool_call_id=tc.id, name=tc.name))
            results.append(
                {
                    "tool": tc.name,
                    "call_id": tc.id,
                    "args": tc.arguments,
                    "status": "success",
                    "result": exec_result,
                }
            )
        except Exception as exc:
            err_detail = f"{type(exc).__name__}: {exc}"
            try:
                await adispatch_custom_event(
                    "tool_result",
                    {
                        "tool": tc.name,
                        "call_id": tc.id,
                        "status": "error",
                        "error": err_detail,
                    },
                )
            except Exception:
                pass

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
            results.append(
                {
                    "tool": tc.name,
                    "call_id": tc.id,
                    "args": tc.arguments,
                    "status": "error",
                    "error": err_detail,
                }
            )
            last_error = err_detail

    current_iterations = int(state.get("iteration_count", 0))
    all_results = list(state.get("tool_results", [])) + results
    existing_tools = list(state.get("tools_used", []))
    all_tools_used = list(dict.fromkeys(existing_tools + executed_tools))

    return {
        "messages": tool_messages,
        "tool_calls": [],
        "tool_results": all_results,
        "tools_used": all_tools_used,
        "iteration_count": current_iterations + 1,
        "error_message": last_error,
    }
