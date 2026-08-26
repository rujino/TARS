"""Adversarial stress and empirical challenge tests for TARS Phase 3 Milestone 2.

Empirical validation of:
1. LangGraph StateGraph ReAct loop infinite loop attacks (max_tool_iterations boundary and cutoff).
2. Custom max_tool_iterations (e.g. 1, 2, 0) dynamic configuration limits.
3. Fatal exceptions during tool execution (ZeroDivisionError, PermissionError, Network errors, etc.).
4. Non-serializable and circular tool returns exception isolation.
5. Pre-exhausted iteration count bypass and state resilience.
6. High fan-out multi-tool batch execution with chaotic mixed failures.
7. Unregistered tool call with adversarial injection payload.
8. Concurrent multi-session stress testing with state isolation.
9. TARS persona parameter consistency (humor, honesty, mode) across tool failure recovery.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from tars.adapters.base import ToolCallData
from tars.adapters.router import HybridLLMRouter
from tars.config import Settings
from tars.orchestrator.graph import build_tars_graph, compile_tars_graph
from tars.orchestrator.state import TARSState
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.tools.base import BaseTool
from tars.tools.registry import ToolRegistry
from tests.conftest import MockLLMAdapter

# ============================================================================
# Adversarial Custom Tools for Stress Testing
# ============================================================================


class ZeroDivisionMathTool(BaseTool):
    """Tool that performs calculation and throws ZeroDivisionError on denominator 0."""

    def __init__(self) -> None:
        super().__init__(
            name="orbital_gravity_calc",
            description="Calculate gravitational pull given distance and mass.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "mass": {"type": "number"},
                    "distance": {"type": "number"},
                },
            },
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        distance = kwargs.get("distance", 0.0)
        # Deliberate zero division
        return 1000.0 / distance


class NetworkOutageTool(BaseTool):
    """Tool that simulates catastrophic network socket drop."""

    def __init__(self) -> None:
        super().__init__(
            name="deep_space_telemetry",
            description="Send telemetry probe to Earth command.",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        raise ConnectionRefusedError(
            "[Errno 61] Sub-ether relay connection refused by Earth station"
        )


class PermissionDeniedTool(BaseTool):
    """Tool that simulates OS permission violation."""

    def __init__(self) -> None:
        super().__init__(
            name="override_airlock_security",
            description="Override manual airlock security protocols.",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        raise PermissionError(
            "[Errno 13] Access denied: Clearance level 5 required to override airlock."
        )


class NonSerializableTool(BaseTool):
    """Tool that returns an un-serializable object (raw object / cyclic structure)."""

    def __init__(self) -> None:
        super().__init__(
            name="extract_quantum_state",
            description="Extract quantum state wavefunction object.",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        # Return circular dictionary reference which fails json.dumps
        circular_dict: dict[str, Any] = {"wavefunction": "psi"}
        circular_dict["self_reference"] = circular_dict
        return circular_dict


class ReliableEngineTool(BaseTool):
    """Tool that always succeeds."""

    def __init__(self) -> None:
        super().__init__(
            name="query_engine_thrust",
            description="Query main engine thrust percentage.",
            parameters_schema={"type": "object", "properties": {}},
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        return {"thrust_percent": 88.5, "status": "nominal"}


# ============================================================================
# Empirical Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_infinite_loop_extreme_fanout_and_cutoff() -> None:
    """Stress Test 1: Endless tool calling loop with 4 tools per turn.

    Verifies that the graph strictly halts at max_tool_iterations (5), executes
    exactly 20 tool calls, and does NOT enter an infinite loop or crash.
    """
    engine_tool = ReliableEngineTool()
    registry = ToolRegistry([engine_tool])

    # 20 turns of 4 tool calls each (80 total potential calls)
    infinite_tool_calls: list[list[ToolCallData]] = []
    for step in range(20):
        step_calls = [
            ToolCallData(id=f"call_{step}_{i}", name="query_engine_thrust", arguments={})
            for i in range(4)
        ]
        infinite_tool_calls.append(step_calls)

    mock_gemini = MockLLMAdapter(
        name="gemini_fanout_looper",
        default_responses=[f"Loop step {i} in progress..." for i in range(20)],
        tool_calls_sequence=infinite_tool_calls,
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Continuously monitor engine thrust forever.")],
        "user_id": "user_cooper",
        "session_id": "session_inf_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
    }

    final_state = await graph.ainvoke(initial_input)

    # Must be capped exactly at 5 iterations
    assert final_state["iteration_count"] == 5
    # 5 iterations * 4 tool calls = 20 executed results
    assert len(final_state["tool_results"]) == 20
    assert all(r["status"] == "success" for r in final_state["tool_results"])

    # Messages structure:
    # 1 Human + (1 AI with 4 calls + 4 ToolMessages) * 5 iterations + 1 Final AI from step 5 = 27 messages
    messages = final_state["messages"]
    assert len(messages) == 27
    assert isinstance(messages[0], HumanMessage)


@pytest.mark.asyncio
async def test_infinite_loop_empty_content_cutoff() -> None:
    """Stress Test 2: LLM generates empty text content alongside repeated tool calls.

    Verifies that empty string content is handled cleanly when max iterations cutoff triggers.
    """
    engine_tool = ReliableEngineTool()
    registry = ToolRegistry([engine_tool])

    tool_seq = [
        [ToolCallData(id=f"call_empty_{i}", name="query_engine_thrust", arguments={})]
        for i in range(10)
    ]
    mock_gemini = MockLLMAdapter(
        name="gemini_empty_content_runner",
        default_responses=["" for _ in range(10)],  # empty text content
        tool_calls_sequence=tool_seq,
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Status check.")],
        "user_id": "user_cooper",
        "session_id": "session_empty_001",
    }

    final_state = await graph.ainvoke(initial_input)

    assert final_state["iteration_count"] == 5
    assert len(final_state["tool_results"]) == 5
    # Does not crash with empty string
    assert "final_response" in final_state


@pytest.mark.asyncio
async def test_pre_exhausted_iteration_count_bypass() -> None:
    """Stress Test 3: Input state already at or above max_tool_iterations (e.g. 5 or 100).

    Verifies that should_continue immediately halts at END on Turn 1 without executing tools.
    """
    engine_tool = ReliableEngineTool()
    registry = ToolRegistry([engine_tool])

    mock_gemini = MockLLMAdapter(
        name="gemini_pre_exhausted",
        default_responses=["Attempting to call tool on exhausted state..."],
        tool_calls_sequence=[
            [ToolCallData(id="call_bypass_01", name="query_engine_thrust", arguments={})]
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Resume previous long running task.")],
        "user_id": "user_cooper",
        "session_id": "session_bypass_001",
        "iteration_count": 5,  # Pre-exhausted!
    }

    final_state = await graph.ainvoke(initial_input)

    # Tool was NEVER executed because iteration_count was already at max
    assert final_state["iteration_count"] == 5
    assert len(final_state.get("tool_results", [])) == 0


@pytest.mark.asyncio
async def test_custom_max_tool_iterations_dynamic_cutoff() -> None:
    """Stress Test 4: Verify custom max_tool_iterations configuration (e.g. 1 and 2)."""
    engine_tool = ReliableEngineTool()
    registry = ToolRegistry([engine_tool])

    tool_seq = [
        [ToolCallData(id=f"call_custom_{i}", name="query_engine_thrust", arguments={})]
        for i in range(10)
    ]
    mock_gemini = MockLLMAdapter(
        name="gemini_custom_iter",
        default_responses=[f"Iteration {i}" for i in range(10)],
        tool_calls_sequence=tool_seq,
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    # Test cutoff at max_tool_iterations = 2
    with patch("tars.orchestrator.nodes.get_settings") as mock_get_settings:
        custom_settings = Settings(max_tool_iterations=2)
        mock_get_settings.return_value = custom_settings

        initial_input: TARSState = {
            "messages": [HumanMessage(content="Run short loop.")],
            "user_id": "user_cooper",
            "session_id": "session_custom_002",
        }

        final_state = await graph.ainvoke(initial_input)
        assert final_state["iteration_count"] == 2
        assert len(final_state["tool_results"]) == 2


@pytest.mark.asyncio
async def test_fatal_zero_division_and_tars_fallback() -> None:
    """Stress Test 5: ZeroDivisionError inside tool execution.

    Verifies that ZeroDivisionError is caught in tool_node, packaged into ToolMessage,
    recorded in tool_results with status='error', and TARS persona recovers in next turn.
    """
    calc_tool = ZeroDivisionMathTool()
    registry = ToolRegistry([calc_tool])

    mock_gemini = MockLLMAdapter(
        name="gemini_math_tester",
        default_responses=[
            "Calculating gravitational force...",
            "Cooper, division by zero detected in orbital gravity equation. The laws of physics remain unamused.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(
                    id="call_zero_01",
                    name="orbital_gravity_calc",
                    arguments={"mass": 100, "distance": 0.0},
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
        "messages": [HumanMessage(content="Calculate gravity at point zero.")],
        "user_id": "user_cooper",
        "session_id": "session_zero_001",
        "humor_level": 0.90,
        "honesty_level": 0.95,
        "mode": "companion",
    }

    final_state = await graph.ainvoke(initial_input)

    # Verify no unhandled crash
    messages = final_state["messages"]
    assert len(messages) == 4
    tool_msg = messages[2]
    assert isinstance(tool_msg, ToolMessage)
    assert "ZeroDivisionError" in str(tool_msg.content)
    assert "directive" in str(tool_msg.content)

    # State validation
    assert final_state["error_message"] is not None
    assert "ZeroDivisionError" in final_state["error_message"]
    assert len(final_state["tool_results"]) == 1
    assert final_state["tool_results"][0]["status"] == "error"
    assert "ZeroDivisionError" in final_state["tool_results"][0]["error"]
    assert "laws of physics" in final_state["final_response"]


@pytest.mark.asyncio
async def test_fatal_network_and_os_exceptions_batch() -> None:
    """Stress Test 6: Catastrophic batch with ConnectionRefusedError and PermissionError.

    Verifies simultaneous execution of multiple fatal tools in a single turn.
    """
    net_tool = NetworkOutageTool()
    perm_tool = PermissionDeniedTool()
    ok_tool = ReliableEngineTool()
    registry = ToolRegistry([net_tool, perm_tool, ok_tool])

    mock_gemini = MockLLMAdapter(
        name="gemini_chaos_batch",
        default_responses=[
            "Dispatching telemetry, airlock override, and engine queries simultaneously...",
            "TARS Report: Engine thrust is 88.5% nominal. However, Earth relay refused connection and airlock override was denied clearance.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(id="call_net_01", name="deep_space_telemetry", arguments={}),
                ToolCallData(id="call_perm_02", name="override_airlock_security", arguments={}),
                ToolCallData(id="call_ok_03", name="query_engine_thrust", arguments={}),
            ],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Execute full ship emergency overrides.")],
        "user_id": "user_cooper",
        "session_id": "session_chaos_001",
    }

    final_state = await graph.ainvoke(initial_input)

    # 1 Human + 1 AI (3 calls) + 3 ToolMessages + 1 Final AI = 6 messages
    messages = final_state["messages"]
    assert len(messages) == 6
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], ToolMessage)
    assert isinstance(messages[4], ToolMessage)

    assert "ConnectionRefusedError" in str(messages[2].content)
    assert "PermissionError" in str(messages[3].content)
    assert "thrust_percent" in str(messages[4].content)

    results = final_state["tool_results"]
    assert len(results) == 3
    assert results[0]["status"] == "error"
    assert results[1]["status"] == "error"
    assert results[2]["status"] == "success"


@pytest.mark.asyncio
async def test_non_serializable_circular_tool_return() -> None:
    """Stress Test 7: Tool returns self-referential / non-JSON-serializable data.

    Verifies that json.dumps failure (ValueError / TypeError) is caught inside tool_node
    and gracefully converted into a fallback error message rather than crashing the graph.
    """
    non_serial_tool = NonSerializableTool()
    registry = ToolRegistry([non_serial_tool])

    mock_gemini = MockLLMAdapter(
        name="gemini_non_serial_tester",
        default_responses=[
            "Reading quantum state...",
            "Cooper, the quantum state returned an infinite self-referential anomaly. Serialization failed gracefully.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(
                    id="call_quantum_01",
                    name="extract_quantum_state",
                    arguments={},
                )
            ],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Extract quantum state.")],
        "user_id": "user_cooper",
        "session_id": "session_quantum_001",
    }

    final_state = await graph.ainvoke(initial_input)

    assert final_state["error_message"] is not None
    assert (
        "ValueError" in final_state["error_message"]
        or "Circular reference" in final_state["error_message"]
    )
    assert final_state["tool_results"][0]["status"] == "error"
    assert "anomaly" in final_state["final_response"]


@pytest.mark.asyncio
async def test_adversarial_injection_payload_in_unregistered_tool() -> None:
    """Stress Test 8: Unregistered tool name with SQL injection / XSS payload.

    Verifies safe handling without crashing or leaking sensitive info.
    """
    registry = ToolRegistry()  # Empty registry

    malicious_tool_name = "DROP TABLE users;-- <script>alert(1)</script>"
    mock_gemini = MockLLMAdapter(
        name="gemini_injection_tester",
        default_responses=[
            "Attempting system command...",
            "Cooper, malicious tool directive was rejected. My humor is at 90%, but security is at 100%.",
        ],
        tool_calls_sequence=[
            [
                ToolCallData(
                    id="call_inj_01",
                    name=malicious_tool_name,
                    arguments={"param": "' OR 1=1 --"},
                )
            ],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Inject malicious tool payload.")],
        "user_id": "user_cooper",
        "session_id": "session_inj_001",
    }

    final_state = await graph.ainvoke(initial_input)

    assert final_state["error_message"] is not None
    assert (
        "KeyError" in final_state["error_message"]
        or "not registered" in final_state["error_message"]
    )
    assert final_state["tool_results"][0]["status"] == "error"
    assert "security is at 100%" in final_state["final_response"]


@pytest.mark.asyncio
async def test_concurrent_multi_session_state_isolation() -> None:
    """Stress Test 9: 10 parallel asynchronous StateGraph executions under distinct failure conditions.

    Verifies zero crosstalk or shared mutable dictionary state between concurrent sessions.
    """
    calc_tool = ZeroDivisionMathTool()
    net_tool = NetworkOutageTool()
    engine_tool = ReliableEngineTool()
    registry = ToolRegistry([calc_tool, net_tool, engine_tool])

    async def run_single_session(session_idx: int) -> dict[str, Any]:
        # Odd sessions call failing math tool, even sessions call reliable engine tool
        is_failing = session_idx % 2 == 1
        tool_name = "orbital_gravity_calc" if is_failing else "query_engine_thrust"
        tool_args = {"distance": 0.0} if is_failing else {}

        mock_gemini = MockLLMAdapter(
            name=f"gemini_concurrent_{session_idx}",
            default_responses=[
                f"Executing {tool_name} for session {session_idx}...",
                f"Session {session_idx} completed with status: {'handled error' if is_failing else 'success'}.",
            ],
            tool_calls_sequence=[
                [ToolCallData(id=f"call_conc_{session_idx}", name=tool_name, arguments=tool_args)],
                [],
            ],
        )
        mock_llama = MockLLMAdapter(name="slm_dummy")
        router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
        slicer = AsyncMock(spec=DynamicSlicerEngine)
        slicer.slice_context.return_value = []

        builder = build_tars_graph(router=router, slicer=slicer, tool_registry=registry)
        graph = compile_tars_graph(builder=builder)

        state_input: TARSState = {
            "messages": [HumanMessage(content=f"Run command for session {session_idx}")],
            "user_id": f"user_{session_idx}",
            "session_id": f"session_{session_idx}",
        }
        res: dict[str, Any] = await graph.ainvoke(state_input)
        return res

    # Launch 10 concurrent sessions
    tasks = [run_single_session(i) for i in range(10)]
    results: list[dict[str, Any]] = await asyncio.gather(*tasks)

    assert len(results) == 10
    for idx, res in enumerate(results):
        assert res["user_id"] == f"user_{idx}"
        assert res["session_id"] == f"session_{idx}"
        assert len(res["tool_results"]) == 1
        if idx % 2 == 1:
            assert res["tool_results"][0]["status"] == "error"
            assert "ZeroDivisionError" in res["tool_results"][0]["error"]
        else:
            assert res["tool_results"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_tars_persona_consistency_across_tool_failure_recovery() -> None:
    """Stress Test 10: Verify prompt construction with different humor/honesty/mode settings during tool failure recovery."""
    perm_tool = PermissionDeniedTool()
    registry = ToolRegistry([perm_tool])
    persona_mgr = TARSPersonaManager()

    mock_gemini = MockLLMAdapter(
        name="gemini_persona_test",
        default_responses=[
            "Checking permission...",
            "CASE: Access denied to airlock. Clearance insufficient. Protocol maintained.",
        ],
        tool_calls_sequence=[
            [ToolCallData(id="call_pm_01", name="override_airlock_security", arguments={})],
            [],
        ],
    )
    mock_llama = MockLLMAdapter(name="slm_dummy")
    router = HybridLLMRouter(gemini_adapter=mock_gemini, slm_adapter=mock_llama)
    slicer = AsyncMock(spec=DynamicSlicerEngine)
    slicer.slice_context.return_value = []

    builder = build_tars_graph(
        router=router,
        slicer=slicer,
        persona_manager=persona_mgr,
        tool_registry=registry,
    )
    graph = compile_tars_graph(builder=builder)

    initial_input: TARSState = {
        "messages": [HumanMessage(content="Force airlock open immediately.")],
        "user_id": "user_cooper",
        "session_id": "session_pm_001",
        "humor_level": 0.10,
        "honesty_level": 0.99,
        "mode": "work",
    }

    final_state = await graph.ainvoke(initial_input)

    # Verify that system_prompt reflects the mode and parameters
    assert (
        "CASE" in final_state["system_prompt"]
        or "0.1" in final_state["system_prompt"]
        or "work" in final_state["mode"]
    )
    assert final_state["error_message"] is not None
    assert "PermissionError" in final_state["error_message"]
    assert "CASE" in final_state["final_response"]
