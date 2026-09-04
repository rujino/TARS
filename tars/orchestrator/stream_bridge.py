"""LangGraph stream event bridge for TARS orchestration pipeline.

Transforms LangGraph astream_events (v2) into a unified AsyncIterator[AgentStreamEvent]
wire protocol generator compatible with FastAPI SSE and WebSocket endpoints.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import BackgroundTasks

from tars.orchestrator.events import AgentStreamEvent

logger = logging.getLogger("tars.orchestrator.stream_bridge")


class LangGraphStreamBridge:
    """Bridges LangGraph execution event streams to unified AgentStreamEvent generator."""

    @classmethod
    async def stream_graph_events(
        cls,
        graph: Any,
        initial_state: dict[str, Any],
        background_tasks: BackgroundTasks | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Consume LangGraph astream_events(version='v2') and yield AgentStreamEvents.

        Wire protocol sequence:
        1. stream_start (initial_state session_id)
        2. [tool_start -> tool_result]* (when tools are invoked)
        3. [token]* (streamed model tokens or chunk deltas)
        4. stream_end (final accumulated content, session_id, tools_used)
        5. done
        (Or error frame on exception)

        Args:
            graph: Compiled LangGraph instance supporting astream_events.
            initial_state: Initial state dictionary containing user_id, session_id, messages, etc.
            background_tasks: Optional FastAPI BackgroundTasks for async execution.

        Yields:
            AgentStreamEvent frames matching the SSE/WS wire protocol.
        """
        active_session_id = str(initial_state.get("session_id") or "")
        accumulated_chunks: list[str] = []
        tools_used: list[str] = []
        emitted_tool_starts: set[str] = set()
        emitted_tool_results: set[str] = set()
        token_count = 0
        stream_ended = False

        # 1. Immediately emit stream_start event before consuming graph events
        yield AgentStreamEvent(type="stream_start", session_id=active_session_id)

        try:
            if not hasattr(graph, "astream_events"):
                raise AttributeError("Graph instance must implement 'astream_events'")

            async for event in graph.astream_events(initial_state, version="v2"):
                ev_type = str(event.get("event", ""))
                ev_name = str(event.get("name", ""))
                data: dict[str, Any] = event.get("data", {}) or {}

                # 2. Track session_id updates from session_node
                if ev_type == "on_chain_end" and ev_name == "session_node":
                    output = data.get("output", {})
                    if isinstance(output, dict) and output.get("session_id"):
                        active_session_id = str(output["session_id"])

                # 3. Handle custom events dispatched via adispatch_custom_event
                elif ev_type == "on_custom_event":
                    if ev_name == "token":
                        delta = str(data.get("delta", ""))
                        if delta:
                            accumulated_chunks.append(delta)
                            token_count += 1
                            curr_content = str(data.get("content") or "".join(accumulated_chunks))
                            yield AgentStreamEvent(
                                type="token",
                                delta=delta,
                                content=curr_content,
                            )

                    elif ev_name == "tool_start":
                        t_name = str(data.get("tool") or data.get("name") or "")
                        t_id = str(
                            data.get("call_id") or data.get("id") or f"call_{len(tools_used)}"
                        )
                        key = f"{t_name}:{t_id}"
                        if key not in emitted_tool_starts:
                            emitted_tool_starts.add(key)
                            if t_name and t_name not in tools_used:
                                tools_used.append(t_name)
                            args = data.get("args") or data.get("arguments") or {}
                            yield AgentStreamEvent(
                                type="tool_start",
                                tool=t_name,
                                call_id=t_id,
                                args=args if isinstance(args, dict) else {"args": args},
                            )

                    elif ev_name == "tool_result":
                        t_name = str(data.get("tool") or data.get("name") or "")
                        t_id = str(data.get("call_id") or data.get("id") or f"call_{t_name}")
                        key = f"{t_name}:{t_id}"
                        if key not in emitted_tool_results:
                            emitted_tool_results.add(key)
                            yield AgentStreamEvent(
                                type="tool_result",
                                tool=t_name,
                                call_id=t_id,
                                status=str(data.get("status", "success")),
                                result=data.get("result"),
                                error=str(data.get("error")) if data.get("error") else None,
                            )

                # 4. Standard LangChain ChatModel streaming chunks
                elif ev_type == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    delta = ""
                    chunk_content = getattr(chunk, "content", None)
                    if chunk_content is not None:
                        delta = str(chunk_content)
                    elif isinstance(chunk, dict):
                        delta = str(chunk.get("content", ""))
                    elif isinstance(chunk, str):
                        delta = chunk

                    if delta:
                        accumulated_chunks.append(delta)
                        token_count += 1
                        yield AgentStreamEvent(
                            type="token",
                            delta=delta,
                            content="".join(accumulated_chunks),
                        )

                # 5. Standard LangChain Tool execution events
                elif ev_type == "on_tool_start":
                    t_name = ev_name
                    t_id = str(
                        event.get("run_id")
                        or event.get("metadata", {}).get("call_id", f"call_{t_name}")
                    )
                    key = f"{t_name}:{t_id}"
                    if key not in emitted_tool_starts:
                        emitted_tool_starts.add(key)
                        if t_name and t_name not in tools_used:
                            tools_used.append(t_name)
                        tool_input = data.get("input", {})
                        yield AgentStreamEvent(
                            type="tool_start",
                            tool=t_name,
                            call_id=t_id,
                            args=tool_input
                            if isinstance(tool_input, dict)
                            else {"input": tool_input},
                        )

                elif ev_type == "on_tool_end":
                    t_name = ev_name
                    t_id = str(
                        event.get("run_id")
                        or event.get("metadata", {}).get("call_id", f"call_{t_name}")
                    )
                    key = f"{t_name}:{t_id}"
                    if key not in emitted_tool_results:
                        emitted_tool_results.add(key)
                        output = data.get("output")
                        has_err = bool(event.get("error"))
                        status = "error" if has_err else "success"
                        err_msg = str(event.get("error")) if has_err else None
                        yield AgentStreamEvent(
                            type="tool_result",
                            tool=t_name,
                            call_id=t_id,
                            status=status,
                            result=output,
                            error=err_msg,
                        )

                # 6. Fallback token extraction from reset_node
                elif ev_type == "on_chain_end" and ev_name == "reset_node":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        reset_msg = output.get("reset_message") or output.get("final_response")
                        if reset_msg and token_count == 0:
                            msg_str = str(reset_msg)
                            accumulated_chunks.append(msg_str)
                            token_count += 1
                            yield AgentStreamEvent(type="token", delta=msg_str, content=msg_str)

                # 7. Fallback tool results extraction from tool_node
                elif ev_type == "on_chain_end" and ev_name == "tool_node":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        # Extract tools_used
                        for t in output.get("tools_used", []):
                            if t not in tools_used:
                                tools_used.append(t)
                        # Extract any tool results not yet emitted
                        for res in output.get("tool_results", []):
                            t_name = res.get("tool", "")
                            t_id = str(res.get("call_id", f"call_{t_name}"))
                            key = f"{t_name}:{t_id}"
                            if key not in emitted_tool_starts:
                                emitted_tool_starts.add(key)
                                yield AgentStreamEvent(
                                    type="tool_start",
                                    tool=t_name,
                                    call_id=t_id,
                                    args=res.get("args", {}),
                                )
                            if key not in emitted_tool_results:
                                emitted_tool_results.add(key)
                                yield AgentStreamEvent(
                                    type="tool_result",
                                    tool=t_name,
                                    call_id=t_id,
                                    status=res.get("status", "success"),
                                    result=res.get("result"),
                                    error=res.get("error"),
                                )

                # 8. Fallback token extraction from llm_node (non-streaming responses)
                elif ev_type == "on_chain_end" and ev_name == "llm_node":
                    output = data.get("output", {})
                    if isinstance(output, dict):
                        tool_calls = output.get("tool_calls", [])
                        final_resp = output.get("final_response")
                        # Only emit token if there are no tool calls pending and no tokens have been streamed yet
                        if not tool_calls and final_resp and token_count == 0:
                            resp_str = str(final_resp)
                            accumulated_chunks.append(resp_str)
                            token_count += 1
                            yield AgentStreamEvent(type="token", delta=resp_str, content=resp_str)

                # 9. Top-level graph completion
                elif ev_type == "on_chain_end" and ev_name == "LangGraph":
                    output = data.get("output", {})
                    final_text = "".join(accumulated_chunks)
                    if (
                        not final_text
                        and isinstance(output, dict)
                        and output.get("final_response")
                    ):
                        final_text = str(output["final_response"])
                        if token_count == 0:
                            yield AgentStreamEvent(
                                type="token", delta=final_text, content=final_text
                            )
                            token_count += 1

                    sid = (
                        output.get("session_id") if isinstance(output, dict) else None
                    ) or active_session_id
                    used = (
                        output.get("tools_used") if isinstance(output, dict) else None
                    ) or tools_used

                    yield AgentStreamEvent(
                        type="stream_end",
                        session_id=sid,
                        content=final_text,
                        tools_used=used,
                    )
                    yield AgentStreamEvent(type="done")
                    stream_ended = True

            # End of async for: if stream_end has not been emitted yet, emit it
            if not stream_ended:
                final_text = "".join(accumulated_chunks)
                yield AgentStreamEvent(
                    type="stream_end",
                    session_id=active_session_id,
                    content=final_text,
                    tools_used=tools_used,
                )
                yield AgentStreamEvent(type="done")
                stream_ended = True

        except Exception as exc:
            logger.error("Error during LangGraph stream execution: %s", exc, exc_info=True)
            yield AgentStreamEvent(type="error", error=str(exc), content=str(exc))
            return


__all__ = ["LangGraphStreamBridge"]
