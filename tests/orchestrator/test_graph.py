"""Integration tests for TARS LangGraph StateGraph Architecture & Routing (Phase 3).

Tests:
1. build_tars_graph structure: all 7 nodes and conditional edges registered.
2. Natural reset branching: session_node -> reset_node -> postprocess_node -> END.
3. Regular dialogue pipeline: session_node -> slicer_node -> prompt_node -> llm_node -> postprocess_node -> END.
4. ReAct tool loop termination: llm_node -> tool_node -> llm_node -> postprocess_node -> END.
5. check_reset edge condition function.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.core.session.manager import SmartSessionManager
from tars.db.models import User
from tars.orchestrator.graph import (
    build_tars_graph,
    check_reset,
    compile_tars_graph,
    create_tars_graph,
)
from tars.orchestrator.state import TARSState
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry
from tests.conftest import MockGeminiAdapter, MockLlamaCppAdapter, MockLLMAdapter


def test_build_tars_graph_registers_all_seven_nodes(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify build_tars_graph registers session_node, reset_node, slicer_node, prompt_node, llm_node, tool_node, postprocess_node."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    slicer = DynamicSlicerEngine()

    builder = build_tars_graph(router=router, slicer=slicer)
    compiled = compile_tars_graph(builder=builder)

    nodes = compiled.nodes.keys()
    assert "session_node" in nodes
    assert "reset_node" in nodes
    assert "slicer_node" in nodes
    assert "prompt_node" in nodes
    assert "llm_node" in nodes
    assert "tool_node" in nodes
    assert "postprocess_node" in nodes


def test_check_reset_edge_condition() -> None:
    """Verify check_reset returns 'reset_node' when is_reset=True, else 'slicer_node'."""
    assert check_reset({"is_reset": True}) == "reset_node"
    assert check_reset({"is_reset": False}) == "slicer_node"
    assert check_reset({}) == "slicer_node"


@pytest.mark.asyncio
async def test_natural_reset_branch_skips_llm_and_executes_reset_flow(
    db_session: AsyncSession,
    seed_test_user: User,
    storage_manager: FileStorageManager,
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify natural reset command routes via reset_node -> postprocess_node -> END, bypassing slicer and llm."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    mock_slicer = AsyncMock(spec=DynamicSlicerEngine)

    graph = create_tars_graph(
        router=router,
        slicer=mock_slicer,
        db_session=db_session,
        storage_manager=storage_manager,
    )

    initial_state: TARSState = {
        "user_id": seed_test_user.id,
        "session_id": "",
        "active_query": "대화 초기화해줘",
        "messages": [HumanMessage(content="대화 초기화해줘")],
    }

    final_state = await graph.ainvoke(initial_state)

    # 1. Reset flag must be set
    assert final_state["is_reset"] is True
    # 2. Reset notice message generated
    assert "기억 장치 초기화 완료" in final_state["final_response"]
    assert "파트너" in final_state["final_response"]
    # 3. Slicer should never have been invoked
    mock_slicer.slice_context.assert_not_called()
    # 4. Messages contains Human and AIMessage
    assert len(final_state["messages"]) == 2
    assert isinstance(final_state["messages"][1], AIMessage)


@pytest.mark.asyncio
async def test_regular_dialogue_pipeline_completes_postprocess(
    db_session: AsyncSession,
    seed_test_user: User,
    storage_manager: FileStorageManager,
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify regular message flows through session -> slicer -> prompt -> llm -> postprocess -> END."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    mock_slicer = AsyncMock(spec=DynamicSlicerEngine)
    mock_slicer.slice_context.return_value = []

    bg_tasks = BackgroundTasks()

    graph = create_tars_graph(
        router=router,
        slicer=mock_slicer,
        db_session=db_session,
        storage_manager=storage_manager,
        background_tasks=bg_tasks,
    )

    initial_state: TARSState = {
        "user_id": seed_test_user.id,
        "session_id": "",
        "active_query": "TARS, what is the mission status?",
        "messages": [HumanMessage(content="TARS, what is the mission status?")],
    }

    final_state = await graph.ainvoke(initial_state)

    assert final_state["is_reset"] is False
    assert final_state["final_response"] != ""
    assert len(final_state["messages"]) == 2
    assert isinstance(final_state["messages"][1], AIMessage)

    # Verify turn was recorded in DB via postprocess_node
    session_mgr = SmartSessionManager(db_session=db_session, storage_manager=storage_manager)
    db_session_obj = await session_mgr.get_session_by_id(final_state["session_id"], user_id=seed_test_user.id)
    assert db_session_obj is not None
    assert len(db_session_obj.messages) == 2


@pytest.mark.asyncio
async def test_react_tool_loop_terminates_at_postprocess() -> None:
    """Verify ReAct loop routes from tool_node back to llm_node, then terminates at postprocess_node."""
    mock_tool = AsyncMock()
    mock_tool.name = "get_coordinates"
    mock_tool.description = "Get navigation coordinates"
    mock_tool.aexecute = AsyncMock(return_value={"x": 102.5, "y": -45.1, "z": 900.0})
    mock_tool.to_gemini_declaration = lambda: {
        "name": "get_coordinates",
        "description": "Get navigation coordinates",
        "parameters": {"type": "object", "properties": {}},
    }

    registry = ToolRegistry()
    registry._tools["get_coordinates"] = mock_tool

    # Turn 1: request tool call
    # Turn 2: answer using tool result
    mock_gemini = MockLLMAdapter(
        name="gemini_tool_tester",
        default_responses=[
            "Checking coordinates...",
            "Current coordinates are locked at X: 102.5, Y: -45.1, Z: 900.0.",
        ],
        tool_calls_sequence=[
            [ToolCallData(id="call_coord_01", name="get_coordinates", arguments={})],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_state: TARSState = {
        "user_id": "user_cooper",
        "session_id": "session_coord_001",
        "active_query": "What are our coordinates?",
        "messages": [HumanMessage(content="What are our coordinates?")],
    }

    final_state = await graph.ainvoke(initial_state)

    assert final_state["iteration_count"] == 1
    assert "get_coordinates" in final_state["tools_used"]
    assert len(final_state["messages"]) == 4
    # 0: HumanMessage
    # 1: AIMessage with tool_calls
    # 2: ToolMessage
    # 3: AIMessage with final response
    assert isinstance(final_state["messages"][2], ToolMessage)
    assert isinstance(final_state["messages"][3], AIMessage)
    assert "coordinates are locked" in final_state["final_response"]
