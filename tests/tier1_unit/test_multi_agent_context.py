"""Unit tests for Multi-Agent Context Injection, Turn Coalescing, and Session Lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from tars.domains.persona.schemas import (
    CharacterInnerState,
    PersonaDefinition,
    RoleType,
    RoutingPattern,
    SubconsciousStatePayload,
    TurnRoutingDecision,
)
from tars.engine.adapters.gemini import GeminiAdapter
from tars.engine.adapters.llamacpp import LlamaCppAdapter
from tars.engine.orchestrator.nodes.companion import (
    companion_dispatch_node,
    companion_postprocess_node,
    companion_session_node,
)


@pytest.mark.unit
def test_gemini_adapter_message_coalescing() -> None:
    """Test that GeminiAdapter coalesces consecutive AIMessages into a single assistant block."""
    adapter = GeminiAdapter(api_key="test_api_key")
    messages: list[BaseMessage] = [
        SystemMessage(content="System instruction"),
        HumanMessage(content="사용자 질문 1"),
        AIMessage(content="첫 번째 답변입니다.", name="miu"),
        AIMessage(content="두 번째 연계 답변입니다.", name="vera"),
        HumanMessage(content="사용자 질문 2"),
    ]

    formatted = adapter._format_messages_for_gemini(messages)

    # Expected: System is excluded in chat body, Human -> user, consecutive AI -> coalesced assistant, Human -> user
    assert len(formatted) == 3
    assert formatted[0] == {"role": "user", "content": "사용자 질문 1"}
    assert formatted[1]["role"] == "assistant"
    assert "[miu]: 첫 번째 답변입니다." in formatted[1]["content"]
    assert "[vera]: 두 번째 연계 답변입니다." in formatted[1]["content"]
    assert formatted[2] == {"role": "user", "content": "사용자 질문 2"}


@pytest.mark.unit
def test_llamacpp_adapter_message_coalescing() -> None:
    """Test that LlamaCppAdapter coalesces consecutive AIMessages into a single assistant block."""
    adapter = LlamaCppAdapter(base_url="http://localhost:8080")
    messages: list[BaseMessage] = [
        HumanMessage(content="사용자 질문"),
        AIMessage(content="[미우]: 야옹!", name="miu"),
        AIMessage(content="[베라]: 정숙하십시오.", name="vera"),
    ]

    formatted = adapter._format_messages_for_slm(messages, system_prompt="System Prompt")

    assert len(formatted) == 3  # system, user, assistant
    assert formatted[0] == {"role": "system", "content": "System Prompt"}
    assert formatted[1] == {"role": "user", "content": "사용자 질문"}
    assert formatted[2]["role"] == "assistant"
    assert "[미우]: 야옹!\n\n[베라]: 정숙하십시오." == formatted[2]["content"]


@pytest.mark.asyncio
async def test_companion_session_node_hot_path() -> None:
    """Test In-Memory Hot Path: When messages history exists in state, skip DB query (0ms DB read)."""
    existing_messages: list[BaseMessage] = [
        HumanMessage(content="어제 이야기한 것 기억해?"),
        AIMessage(content="[미우]: 당연히 기억한다냥!"),
    ]

    state = {
        "user_id": "test_user",
        "session_id": "session_123",
        "active_query": "그럼 다음 단계 진행하자.",
        "messages": existing_messages,
    }

    mock_session_mgr = AsyncMock()

    result = await companion_session_node(
        state=state,  # type: ignore[arg-type]
        session_manager=mock_session_mgr,
    )

    # Verify SmartSessionManager.route_session was NOT called (Hot Path 0ms DB Read)
    mock_session_mgr.route_session.assert_not_called()
    assert result["session_id"] == "session_123"
    assert len(result["messages"]) == 3
    assert result["messages"][0].content == "어제 이야기한 것 기억해?"
    assert result["messages"][1].content == "[미우]: 당연히 기억한다냥!"
    assert result["messages"][2].content == "그럼 다음 단계 진행하자."


@pytest.mark.asyncio
async def test_companion_session_node_cold_start() -> None:
    """Test Cold Start: When messages history is empty, route_session is called 1 time to hydrate from DB."""
    state = {
        "user_id": "test_user",
        "session_id": "session_cold",
        "active_query": "새로운 대화를 시작해볼까?",
        "messages": [],
    }

    mock_session = MagicMock()
    mock_session.id = "session_cold"
    mock_working_memory = [
        HumanMessage(content="이전 세션 질문"),
        AIMessage(content="[미우]: 이전 세션 답변이다냥"),
    ]

    mock_session_mgr = AsyncMock()
    mock_session_mgr.route_session.return_value = (mock_session, mock_working_memory, MagicMock())

    result = await companion_session_node(
        state=state,  # type: ignore[arg-type]
        session_manager=mock_session_mgr,
    )

    # Verify SmartSessionManager.route_session WAS called exactly once for hydration
    mock_session_mgr.route_session.assert_awaited_once_with(
        user_id="test_user",
        requested_session_id="session_cold",
        incoming_message="새로운 대화를 시작해볼까?",
        background_tasks=None,
    )
    assert result["session_id"] == "session_cold"
    assert len(result["messages"]) == 3
    assert result["messages"][0].content == "이전 세션 질문"
    assert result["messages"][1].content == "[미우]: 이전 세션 답변이다냥"
    assert result["messages"][2].content == "새로운 대화를 시작해볼까?"


@pytest.mark.asyncio
async def test_companion_dispatch_node_canonical_formatting() -> None:
    """Test companion_dispatch_node formats multi-speaker outputs into canonical speaker-tagged responses."""
    p_miu = PersonaDefinition(
        id="miu",
        name="미우",
        role_type=RoleType.PRIMARY_COMPANION,
        base_prompt="미우 프롬프트",
    )
    p_vera = PersonaDefinition(
        id="vera",
        name="베라",
        role_type=RoleType.ADVISOR,
        base_prompt="베라 프롬프트",
    )

    mock_registry = MagicMock()
    mock_registry.list_all.return_value = [p_miu, p_vera]
    mock_registry.get.side_effect = lambda pid: p_miu if pid == "miu" else p_vera
    mock_registry.render_system_prompt.return_value = "Rendered System Prompt"
    mock_registry.synthesize_inner_state.return_value = CharacterInnerState(
        my_vibe="활기참", my_agenda="주인 위로하기"
    )

    mock_router = AsyncMock()
    # First call: Miu, Second call: Vera
    mock_router.route_and_generate.side_effect = [
        "주인님 반갑다냥!",
        "차 한 잔 준비해 드리겠습니다.",
    ]

    routing = TurnRoutingDecision(
        pattern=RoutingPattern.TAG_TEAM_REMEDIATION,
        primary_speaker_id="miu",
        secondary_speaker_id="vera",
        dialogue_tone="comfort",
        turn_intent="greeting",
    )
    subconscious = SubconsciousStatePayload(
        context_summary="일상 대화",
        master_state="안정",
        expected_reaction=None,
        prediction_feedback=None,
    )

    state = {
        "user_id": "test_user",
        "session_id": "sess_1",
        "active_query": "안녕 애들아!",
        "messages": [HumanMessage(content="안녕 애들아!")],
        "active_personas": [p_miu, p_vera],
        "turn_routing": routing,
        "subconscious": subconscious,
    }

    result = await companion_dispatch_node(
        state=state,  # type: ignore[arg-type]
        registry=mock_registry,
        router=mock_router,
    )

    assert len(result["messages"]) == 2
    assert result["messages"][0].content == "[미우]: 주인님 반갑다냥!"
    assert result["messages"][1].content == "[베라]: 차 한 잔 준비해 드리겠습니다."
    assert "[미우]: 주인님 반갑다냥!\n\n[베라]: 차 한 잔 준비해 드리겠습니다." == result["final_response"]


@pytest.mark.asyncio
async def test_companion_postprocess_node_persistence() -> None:
    """Test companion_postprocess_node persists completed multi-companion turn as single assistant record."""
    mock_session_mgr = AsyncMock()
    mock_storage = MagicMock()
    mock_bg_tasks = MagicMock()

    state = {
        "user_id": "user_42",
        "session_id": "session_99",
        "active_query": "오늘 수고했어",
        "final_response": "[미우]: 주인님도 고생했다냥!\n\n[베라]: 좋은 밤 되십시오.",
    }

    await companion_postprocess_node(
        state=state,  # type: ignore[arg-type]
        session_manager=mock_session_mgr,
        storage_manager=mock_storage,
        background_tasks=mock_bg_tasks,
    )

    # 1. DB Turn persistence called with single combined assistant content
    mock_session_mgr.record_turn.assert_awaited_once_with(
        session_id="session_99",
        user_id="user_42",
        user_content="오늘 수고했어",
        assistant_content="[미우]: 주인님도 고생했다냥!\n\n[베라]: 좋은 밤 되십시오.",
    )

    # 2. Background knowledge extraction scheduled
    mock_bg_tasks.add_task.assert_called_once()
