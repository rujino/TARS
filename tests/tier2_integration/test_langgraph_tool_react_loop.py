"""Tier 2 Integration Tests: LangGraph StateGraph ReAct Loop with Tools.

Verifies:
1. Tool Calling ReAct Cycle:
   START -> slicer_node -> prompt_node -> llm_node (requests tool) ->
   tool_node (executes tool & produces ToolMessage) ->
   llm_node (generates final answer using tool result) -> END.
2. Multi-Step Chained Tool Execution (search -> get detail -> answer).
3. Max Iterations Circuit Breaker: Prevents infinite looping when LLM continuously requests tools.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.orchestrator.graph import build_tars_graph, compile_tars_graph
from tars.orchestrator.state import TARSState
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.google.auth import GoogleAuthHelper
from tars.tools.google.calendar import GoogleCalendarAdapter
from tars.tools.google.gmail import GmailAdapter
from tars.tools.registry import ToolRegistry
from tests.conftest import MockLLMAdapter


@pytest.mark.asyncio
async def test_single_tool_react_cycle() -> None:
    """Verify single tool call execution and final response generation via ReAct loop."""
    calendar_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    registry = ToolRegistry(calendar_adapter.get_tools())

    # Turn 1: Requests calendar_list_events
    # Turn 2: Generates final response
    mock_gemini = MockLLMAdapter(
        name="gemini_tool_runner",
        default_responses=[
            "Checking your mission schedule now, Cooper.",
            "Cooper, you have the Endurance Mission Briefing scheduled at 10:00 UTC.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(
                    id="call_cal_01",
                    name="calendar_list_events",
                    arguments={"max_results": 2},
                )
            ],
            [],  # Turn 2 has no tool calls, yielding final response
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")

    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="What events are on my calendar today?")],
        "user_id": "user_cooper",
        "session_id": "session_cal_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
    }

    final_state = await graph.ainvoke(initial_input)

    # Message sequence verification:
    # 0: HumanMessage ("What events are on my calendar today?")
    # 1: AIMessage (content="Checking your mission schedule...", tool_calls=[...])
    # 2: ToolMessage (content=JSON results of calendar_list_events)
    # 3: AIMessage (content="Cooper, you have the Endurance Mission Briefing...")
    messages = final_state["messages"]
    assert len(messages) == 4
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], AIMessage)

    # Tool message validation
    tool_msg = messages[2]
    assert tool_msg.tool_call_id == "call_cal_01"
    assert tool_msg.name == "calendar_list_events"
    assert "Endurance Mission Briefing" in str(tool_msg.content)

    # State metadata validation
    assert final_state["iteration_count"] == 1
    assert len(final_state["tool_results"]) == 1
    assert final_state["tool_results"][0]["status"] == "success"
    assert "Endurance Mission Briefing" in final_state["final_response"]


@pytest.mark.asyncio
async def test_chained_multi_tool_react_loop() -> None:
    """Verify multi-step tool chaining (search unread email -> fetch email detail -> answer)."""
    gmail_adapter = GmailAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    registry = ToolRegistry(gmail_adapter.get_tools())

    # Step 1: Tool call search_messages
    # Step 2: Tool call get_message
    # Step 3: Final Answer
    mock_gemini = MockLLMAdapter(
        name="gemini_chain_runner",
        default_responses=[
            "Searching for unread messages...",
            "Fetching message details for msg_001...",
            "Cooper, you have an unread email regarding Trajectory Calculation from yourself.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(
                    id="call_search_01",
                    name="gmail_search_messages",
                    arguments={"query": "is:unread"},
                )
            ],
            [
                ToolCallData(
                    id="call_get_02",
                    name="gmail_get_message",
                    arguments={"message_id": "msg_001"},
                )
            ],
            [],  # Final step
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Check my unread emails and summarize them.")],
        "user_id": "user_cooper",
        "session_id": "session_gmail_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
    }

    final_state = await graph.ainvoke(initial_input)

    # 1 Human + (1 AI + 1 Tool) + (1 AI + 1 Tool) + 1 Final AI = 6 messages
    messages = final_state["messages"]
    assert len(messages) == 6
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], AIMessage)
    assert isinstance(messages[4], ToolMessage)
    assert isinstance(messages[5], AIMessage)

    assert final_state["iteration_count"] == 2
    assert len(final_state["tool_results"]) == 2
    assert "Trajectory Calculation" in final_state["final_response"]


@pytest.mark.asyncio
async def test_max_tool_iterations_safety_limit() -> None:
    """Verify loop safely terminates at max_tool_iterations when LLM loops endlessly."""
    calendar_adapter = GoogleCalendarAdapter(auth_helper=GoogleAuthHelper(mock_mode=True))
    registry = ToolRegistry(calendar_adapter.get_tools())

    # Endless tool call generator
    inf_tool_calls: list[list[ToolCallData]] = [
        [ToolCallData(id=f"call_inf_{i}", name="calendar_list_events", arguments={})]
        for i in range(20)
    ]

    mock_gemini = MockLLMAdapter(
        name="gemini_infinite_loop",
        default_responses=[f"Listing events attempt {i}" for i in range(20)],
        tool_calls_sequence=inf_tool_calls,
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: dict[str, Any] = {
        "messages": [HumanMessage(content="Keep checking calendar.")],
        "user_id": "user_cooper",
        "session_id": "session_loop_001",
        "iteration_count": 0,
    }

    final_state = await graph.ainvoke(initial_input)

    # Must terminate without infinite loop and reach max iterations (default 5)
    assert final_state["iteration_count"] == 5
