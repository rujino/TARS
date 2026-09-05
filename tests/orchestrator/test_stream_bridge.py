"""Tests for LangGraphStreamBridge (tars/orchestrator/stream_bridge.py).

Verifies:
1. Normal dialogue token streaming: stream_start -> token -> stream_end -> done.
2. Natural language reset streaming: stream_start -> token -> stream_end -> done.
3. ReAct tool execution streaming: stream_start -> tool_start -> tool_result -> token -> stream_end -> done.
4. Tool error resilience: graceful tool_result(error) frame emission.
5. Abnormal error handling: stream_start -> error frame emission.
6. Standard LangChain callback events: on_chat_model_stream, on_tool_start, on_tool_end.
7. SSE and WebSocket serialization compatibility.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tars.adapters.base import LLMResponse, ToolCallData
from tars.core.session.models import SessionRoutingAction, SessionRoutingDecision
from tars.orchestrator.graph import build_tars_graph
from tars.orchestrator.stream_bridge import LangGraphStreamBridge
from tars.services.agent_chat import AgentStreamEvent
from tars.tools.base import BaseTool


class DummyEchoTool(BaseTool):
    """Dummy tool for testing ReAct execution streaming."""

    def __init__(self) -> None:
        super().__init__(
            name="echo_tool",
            description="Echo back input message",
            parameters_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        text = kwargs.get("text", "")
        return {"echo": text, "status": "ok"}


class DummyFailingTool(BaseTool):
    """Dummy failing tool for testing fallback execution streaming."""

    def __init__(self) -> None:
        super().__init__(
            name="failing_tool",
            description="Always fails with an error",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        raise RuntimeError("Subsystem failure detected")


# ============================================================================
# 1. Normal Conversation Streaming Tests
# ============================================================================


@pytest.mark.asyncio
async def test_stream_bridge_happy_path() -> None:
    """Verify normal conversational flow yields stream_start -> token -> stream_end -> done."""
    mock_router = MagicMock()
    mock_router.route_and_generate_response = AsyncMock(
        return_value=LLMResponse(content="안녕하세요, 파트너. TARS 가동 준비 완료되었습니다.")
    )

    mock_slicer = MagicMock()
    mock_slicer.slice_context = AsyncMock(return_value=[])

    mock_persona = MagicMock()
    mock_persona.build_system_prompt = MagicMock(return_value="TARS Test System Prompt")

    compiled_graph = build_tars_graph(
        router=mock_router,
        slicer=mock_slicer,
        persona_manager=mock_persona,
    ).compile()

    initial_state = {
        "user_id": "usr_stream_001",
        "session_id": "sess_stream_001",
        "active_query": "상태 보고해",
        "messages": [],
    }

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=compiled_graph,
        initial_state=initial_state,
    ):
        events.append(event)

    event_types = [e.type for e in events]
    assert event_types[0] == "stream_start"
    assert "token" in event_types
    assert event_types[-2] == "stream_end"
    assert event_types[-1] == "done"

    # Verify session ID and content
    assert events[0].session_id == "sess_stream_001"
    stream_end = events[-2]
    assert stream_end.session_id == "sess_stream_001"
    assert "안녕하세요" in (stream_end.content or "")
    assert stream_end.tools_used == []


@pytest.mark.asyncio
async def test_stream_bridge_direct_token_streaming() -> None:
    """Verify route_and_stream yielding multiple tokens produces individual token events."""
    mock_graph = MagicMock()

    async def mock_stream_events(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        tokens = ["TARS ", "online ", "and ", "ready."]
        accum = ""
        for tok in tokens:
            accum += tok
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": tok},
            }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_response": accum, "session_id": "sess_stream_002"}},
        }

    mock_graph.astream_events = mock_stream_events

    initial_state = {
        "user_id": "usr_stream_002",
        "session_id": "sess_stream_002",
        "active_query": "Status check",
        "messages": [],
    }

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=mock_graph,
        initial_state=initial_state,
    ):
        events.append(event)

    token_events = [e for e in events if e.type == "token"]
    assert len(token_events) == 4
    deltas = [e.delta for e in token_events]
    assert deltas == ["TARS ", "online ", "and ", "ready."]

    stream_end = next(e for e in events if e.type == "stream_end")
    assert stream_end.content == "TARS online and ready."


# ============================================================================
# 2. Reset Command Streaming Tests
# ============================================================================


@pytest.mark.asyncio
async def test_stream_bridge_reset_command() -> None:
    """Verify natural language reset command yields reset token and ends cleanly."""
    mock_session_mgr = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "sess_reset_new"
    mock_session_mgr.route_session = AsyncMock(
        return_value=(
            mock_session,
            [],
            SessionRoutingDecision(
                action=SessionRoutingAction.NATURAL_RESET,
                session_id="sess_reset_new",
                is_reset=True,
                reason="explicit_reset_command",
            ),
        )
    )
    compiled_graph = build_tars_graph(
        router=MagicMock(),
        slicer=MagicMock(),
        session_manager=mock_session_mgr,
    ).compile()

    initial_state = {
        "user_id": "usr_reset_001",
        "session_id": "sess_reset_old",
        "active_query": "기억 장치 초기화해줘",
        "messages": [],
        "mode": "companion",
    }

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=compiled_graph,
        initial_state=initial_state,
    ):
        events.append(event)

    event_types = [e.type for e in events]
    assert event_types[0] == "stream_start"
    assert "token" in event_types
    assert event_types[-2] == "stream_end"
    assert event_types[-1] == "done"

    token_event = next(e for e in events if e.type == "token")
    assert "기억 장치 초기화 완료" in (token_event.content or "")
    assert events[-2].session_id == "sess_reset_new"


# ============================================================================
# 3. ReAct Tool Calling Streaming Tests
# ============================================================================


@pytest.mark.asyncio
async def test_stream_bridge_react_tool_calling() -> None:
    """Verify ReAct tool execution yields tool_start -> tool_result -> token -> stream_end."""
    from tars.tools.registry import ToolRegistry

    registry = ToolRegistry([DummyEchoTool()])

    turn1_resp = LLMResponse(
        content="에코 도구를 실행합니다.",
        tool_calls=[
            ToolCallData(
                id="call_echo_001",
                name="echo_tool",
                arguments={"text": "테스트 메시지"},
            )
        ],
    )
    turn2_resp = LLMResponse(
        content="도구 실행이 완료되었습니다: 테스트 메시지",
        tool_calls=[],
    )

    call_count = 0

    async def mock_generate(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return turn1_resp
        return turn2_resp

    mock_router = MagicMock()
    mock_router.route_and_generate_response = AsyncMock(side_effect=mock_generate)

    mock_slicer = MagicMock()
    mock_slicer.slice_context = AsyncMock(return_value=[])

    mock_persona = MagicMock()
    mock_persona.build_system_prompt = MagicMock(return_value="TARS Persona")

    compiled_graph = build_tars_graph(
        router=mock_router,
        slicer=mock_slicer,
        persona_manager=mock_persona,
        tool_registry=registry,
    ).compile()

    initial_state = {
        "user_id": "usr_tool_001",
        "session_id": "sess_tool_001",
        "active_query": "에코 테스트 실행해줘",
        "messages": [],
    }

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=compiled_graph,
        initial_state=initial_state,
    ):
        events.append(event)

    event_types = [e.type for e in events]
    assert "stream_start" in event_types
    assert "tool_start" in event_types
    assert "tool_result" in event_types
    assert "token" in event_types
    assert "stream_end" in event_types
    assert "done" in event_types

    # Validate tool_start
    t_start = next(e for e in events if e.type == "tool_start")
    assert t_start.tool == "echo_tool"
    assert t_start.call_id == "call_echo_001"
    assert t_start.args == {"text": "테스트 메시지"}

    # Validate tool_result
    t_res = next(e for e in events if e.type == "tool_result")
    assert t_res.tool == "echo_tool"
    assert t_res.call_id == "call_echo_001"
    assert t_res.status == "success"
    assert t_res.result == {"echo": "테스트 메시지", "status": "ok"}

    # Validate stream_end tools_used
    s_end = next(e for e in events if e.type == "stream_end")
    assert "echo_tool" in (s_end.tools_used or [])


@pytest.mark.asyncio
async def test_stream_bridge_failing_tool_graceful_fallback() -> None:
    """Verify tool failure emits tool_result with status='error' and continues to synthesize response."""
    from tars.tools.registry import ToolRegistry

    registry = ToolRegistry([DummyFailingTool()])

    turn1_resp = LLMResponse(
        content="장애 도구를 호출합니다.",
        tool_calls=[
            ToolCallData(
                id="call_fail_001",
                name="failing_tool",
                arguments={},
            )
        ],
    )
    turn2_resp = LLMResponse(
        content="하위 시스템 오류를 인지했습니다. 대체 절차를 제안합니다.",
        tool_calls=[],
    )

    call_count = 0

    async def mock_generate(*args: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return turn1_resp
        return turn2_resp

    mock_router = MagicMock()
    mock_router.route_and_generate_response = AsyncMock(side_effect=mock_generate)

    mock_slicer = MagicMock()
    mock_slicer.slice_context = AsyncMock(return_value=[])

    mock_persona = MagicMock()
    mock_persona.build_system_prompt = MagicMock(return_value="TARS Persona")

    compiled_graph = build_tars_graph(
        router=mock_router,
        slicer=mock_slicer,
        persona_manager=mock_persona,
        tool_registry=registry,
    ).compile()

    initial_state = {
        "user_id": "usr_fail_001",
        "session_id": "sess_fail_001",
        "active_query": "실패 도구 호출",
        "messages": [],
    }

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=compiled_graph,
        initial_state=initial_state,
    ):
        events.append(event)

    t_res = next(e for e in events if e.type == "tool_result")
    assert t_res.tool == "failing_tool"
    assert t_res.status == "error"
    assert "Subsystem failure detected" in (t_res.error or "")

    s_end = next(e for e in events if e.type == "stream_end")
    assert "failing_tool" in (s_end.tools_used or [])
    assert "대체 절차" in (s_end.content or "")


# ============================================================================
# 4. Error Handling Tests (Task 4.2)
# ============================================================================


@pytest.mark.asyncio
async def test_stream_bridge_catches_graph_exception() -> None:
    """Verify exceptions during graph execution emit type='error' and terminate safely."""
    mock_graph = MagicMock()

    async def mock_faulty_astream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "on_chain_start", "name": "session_node", "data": {}}
        raise RuntimeError("Fatal graph runtime crash")

    mock_graph.astream_events = mock_faulty_astream

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=mock_graph,
        initial_state={"session_id": "sess_err_001"},
    ):
        events.append(event)

    assert any(e.type == "error" for e in events)
    assert events[-1].type == "error"
    assert "Fatal graph runtime crash" in (events[-1].error or "")


@pytest.mark.asyncio
async def test_stream_bridge_invalid_graph_object() -> None:
    """Verify passing an object without astream_events yields error frame."""
    invalid_graph = object()

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=invalid_graph,
        initial_state={"session_id": "sess_invalid"},
    ):
        events.append(event)

    assert any(e.type == "error" for e in events)
    assert events[-1].type == "error"
    assert "astream_events" in (events[-1].error or "")


# ============================================================================
# 5. Standard LangChain Events & SSE/WS Serialization
# ============================================================================


@pytest.mark.asyncio
async def test_stream_bridge_standard_langchain_events() -> None:
    """Verify bridge processes standard on_chat_model_stream, on_tool_start, and on_tool_end."""
    mock_graph = MagicMock()

    async def mock_astream(*args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        # 1. on_tool_start
        yield {
            "event": "on_tool_start",
            "name": "calc_tool",
            "run_id": "run_calc_99",
            "data": {"input": {"expr": "1+1"}},
        }
        # 2. on_tool_end
        yield {
            "event": "on_tool_end",
            "name": "calc_tool",
            "run_id": "run_calc_99",
            "data": {"output": "2"},
        }
        # 3. on_chat_model_stream
        yield {
            "event": "on_chat_model_stream",
            "data": {"chunk": "Result is 2."},
        }
        # 4. LangGraph complete
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"session_id": "sess_lc_001", "tools_used": ["calc_tool"]}},
        }

    mock_graph.astream_events = mock_astream

    events: list[AgentStreamEvent] = []
    async for event in LangGraphStreamBridge.stream_graph_events(
        graph=mock_graph,
        initial_state={"session_id": "sess_lc_001"},
    ):
        events.append(event)

    types = [e.type for e in events]
    assert types == ["stream_start", "tool_start", "tool_result", "token", "stream_end", "done"]

    # Verify SSE formatting
    for e in events:
        sse = e.to_sse_event()
        assert sse.startswith("event: ")
        assert "\ndata: " in sse
        assert sse.endswith("\n\n")

    # Verify WebSocket dict formatting
    for e in events:
        ws_dict = e.to_ws_dict()
        assert "type" in ws_dict
        assert ws_dict["type"] == e.type
