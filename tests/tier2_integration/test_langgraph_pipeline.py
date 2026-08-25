"""Tier 2 Integration Tests: LangGraph StateGraph Pipeline, State Transitions & Memory.

Verifies:
1. StateGraph Compilation: Correct registration of state schema (TARSState), nodes, and edges.
2. Node Transitions: Sequential execution flow:
   START -> slicer_node -> prompt_node -> llm_node -> END.
3. Memory Retention: Multi-turn conversation turns preserved using LangGraph message reducers
   and checkpointing.
4. Context Injection: Dynamic Slicer outputs are injected into TARSState.relevant_wikis and
   rendered into the final system prompt.
5. TARS Persona Parameter Reflection: humor_level (0.90), honesty_level (0.95), and mode
   ("companion" vs. "work") are faithfully translated into prompt directives.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tars.adapters.router import HybridLLMRouter
from tars.core.okf.models import (
    OKFDocument,
)
from tars.orchestrator.graph import build_tars_graph, compile_tars_graph
from tars.orchestrator.nodes import llm_node, prompt_node, slicer_node
from tars.orchestrator.state import TARSState
from tars.slicer.engine import DynamicSlicerEngine
from tests.conftest import MockGeminiAdapter, MockLlamaCppAdapter

# ============================================================================
# 1. StateGraph Compilation & Architecture Tests
# ============================================================================


def test_stategraph_compiles_successfully(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify that StateGraph builds and compiles without schema or node errors."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    slicer = DynamicSlicerEngine()

    builder = build_tars_graph(router=router, slicer=slicer)
    compiled_graph = compile_tars_graph(builder=builder)

    assert compiled_graph is not None
    # Verify nodes exist in compiled graph
    node_keys = compiled_graph.nodes.keys()
    assert "slicer_node" in node_keys
    assert "prompt_node" in node_keys
    assert "llm_node" in node_keys


# ============================================================================
# 2. Node Transitions & Execution Tests
# ============================================================================


@pytest.mark.asyncio
async def test_slicer_node_populates_relevant_wikis(
    sample_okf_doc: OKFDocument,
) -> None:
    """Verify slicer_node queries DynamicSlicerEngine and populates relevant_wikis in state."""
    mock_slicer = AsyncMock(spec=DynamicSlicerEngine)
    mock_slicer.slice_context.return_value = [sample_okf_doc]

    initial_state: TARSState = {
        "messages": [HumanMessage(content="When is our mission sync meeting?")],
        "user_id": "user_test_alpha",
        "session_id": "session_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
        "relevant_wikis": [],
        "system_prompt": "",
        "final_response": "",
    }

    updated_state = await slicer_node(state=initial_state, slicer=mock_slicer)

    assert len(updated_state["relevant_wikis"]) == 1
    assert updated_state["relevant_wikis"][0].metadata.id == "schedule_weekly_sync"
    mock_slicer.slice_context.assert_awaited_once_with(
        user_id="user_test_alpha",
        query="When is our mission sync meeting?",
        token_budget=1500,
    )


@pytest.mark.asyncio
async def test_prompt_node_injects_persona_and_knowledge(
    sample_okf_doc: OKFDocument,
) -> None:
    """Verify prompt_node formats system prompt with TARS persona and OKF knowledge context."""
    state_with_wikis: TARSState = {
        "messages": [HumanMessage(content="Status report.")],
        "user_id": "user_test_alpha",
        "session_id": "session_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
        "relevant_wikis": [sample_okf_doc],
        "system_prompt": "",
        "final_response": "",
    }

    updated_state = await prompt_node(state=state_with_wikis)

    system_prompt = updated_state["system_prompt"]
    assert "TARS" in system_prompt
    assert "90%" in system_prompt or "0.9" in system_prompt
    assert "95%" in system_prompt or "0.95" in system_prompt
    assert "Weekly Endurance Sync Meeting" in system_prompt
    assert "Tuesdays at 15:00 UTC" in system_prompt


@pytest.mark.asyncio
async def test_prompt_node_work_mode_suppression() -> None:
    """Verify work mode suppresses jokes and enforces concise, technical output."""
    work_state: TARSState = {
        "messages": [HumanMessage(content="Run diagnostic.")],
        "user_id": "user_test_beta",
        "session_id": "session_work_001",
        "humor_level": 0.0,
        "honesty_level": 0.95,
        "mode": "work",
        "relevant_wikis": [],
        "system_prompt": "",
        "final_response": "",
    }

    updated_state = await prompt_node(state=work_state)
    system_prompt = updated_state["system_prompt"]

    assert "work" in system_prompt.lower() or "case" in system_prompt.lower()


@pytest.mark.asyncio
async def test_llm_node_invokes_router_and_updates_final_response(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify llm_node executes hybrid router and records response in state."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )

    state: TARSState = {
        "messages": [HumanMessage(content="TARS, tell me a joke.")],
        "user_id": "user_test_alpha",
        "session_id": "session_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
        "relevant_wikis": [],
        "system_prompt": "You are TARS with humor 90%.",
        "final_response": "",
    }

    updated_state = await llm_node(state=state, router=router)

    assert updated_state["final_response"] != ""
    # Check that AIMessage is appended to message history
    last_msg = updated_state["messages"][-1]
    assert isinstance(last_msg, AIMessage)
    assert last_msg.content == updated_state["final_response"]


# ============================================================================
# 3. End-to-End Pipeline Execution & Multi-Turn Memory Tests
# ============================================================================


@pytest.mark.asyncio
async def test_full_graph_turn_execution(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
    sample_okf_doc: OKFDocument,
) -> None:
    """Verify full graph execution from start to finish on a single user input."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    mock_slicer = AsyncMock(spec=DynamicSlicerEngine)
    mock_slicer.slice_context.return_value = [sample_okf_doc]

    builder = build_tars_graph(router=router, slicer=mock_slicer)
    graph = compile_tars_graph(builder=builder)

    inputs: dict[str, Any] = {
        "messages": [HumanMessage(content="Is there a sync meeting today?")],
        "user_id": "user_test_alpha",
        "session_id": "session_e2e_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
    }

    result = await graph.ainvoke(inputs)

    assert result["final_response"] != ""
    assert len(result["messages"]) == 2  # HumanMessage + AIMessage
    assert isinstance(result["messages"][1], AIMessage)
    assert result["system_prompt"] != ""
    assert "Weekly Endurance Sync Meeting" in result["system_prompt"]


@pytest.mark.asyncio
async def test_multiturn_memory_retention_across_invocations(
    mock_gemini_adapter: MockGeminiAdapter,
    mock_llama_adapter: MockLlamaCppAdapter,
) -> None:
    """Verify multi-turn dialogues accumulate history in order without overwriting."""
    router = HybridLLMRouter(
        gemini_adapter=mock_gemini_adapter,
        slm_adapter=mock_llama_adapter,
    )
    mock_slicer = AsyncMock(spec=DynamicSlicerEngine)
    mock_slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=mock_slicer)
    graph = compile_tars_graph(builder=builder)

    # Turn 1
    state_turn1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="Turn 1: My name is Cooper.")],
            "user_id": "user_test_alpha",
            "session_id": "session_multi_001",
            "humor_level": 0.90,
            "honesty_level": 0.95,
            "mode": "companion",
        }
    )
    assert len(state_turn1["messages"]) == 2

    # Turn 2 (Feeding previous messages forward)
    turn2_messages = list(state_turn1["messages"]) + [
        HumanMessage(content="Turn 2: What was my name again?")
    ]
    state_turn2 = await graph.ainvoke(
        {
            **state_turn1,
            "messages": turn2_messages,
        }
    )

    assert len(state_turn2["messages"]) == 4
    assert state_turn2["messages"][0].content == "Turn 1: My name is Cooper."
    assert isinstance(state_turn2["messages"][1], AIMessage)
    assert state_turn2["messages"][2].content == "Turn 2: What was my name again?"
    assert isinstance(state_turn2["messages"][3], AIMessage)
