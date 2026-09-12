"""Session lifecycle and reset handling nodes for TARS orchestration pipeline."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
)
from sqlalchemy import select

from tars.core.session.detector import RESET_COMMAND_REGEX
from tars.core.session.schemas import SessionRoutingAction, SessionRoutingDecision
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.persona.models import TARSSettings
from tars.engine.orchestrator.state import (
    DEFAULT_HONESTY_LEVEL,
    DEFAULT_HUMOR_LEVEL,
    DEFAULT_MODE,
    TARSState,
)

if TYPE_CHECKING:
    from fastapi import BackgroundTasks
    from sqlalchemy.ext.asyncio import AsyncSession

    from tars.core.session.manager import SmartSessionManager
    from tars.engine.adapters.router import HybridLLMRouter

logger = logging.getLogger("tars.engine.orchestrator.nodes.session")


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


async def session_node(
    state: TARSState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Evaluate session lifecycle, load persona settings, and prepare working memory.

    Args:
        state: Current graph state containing user_id, session_id, and active_query or messages.
        session_manager: Optional pre-configured SmartSessionManager instance.
        db_session: Optional AsyncSession for database operations.
        storage_manager: Optional FileStorageManager instance.
        router: Optional HybridLLMRouter instance.
        background_tasks: Optional FastAPI BackgroundTasks for async archiving/extraction.

    Returns:
        State update dictionary containing session_id, humor_level, honesty_level,
        mode, routing_decision, is_reset, and hydrated messages history.
    """
    user_id = state.get("user_id", "")
    session_id = state.get("session_id")
    messages = state.get("messages", [])
    extracted_query = _extract_active_query(messages)
    active_query = extracted_query if extracted_query else state.get("active_query", "")

    # 1. Fetch user persona parameters from DB (or state/defaults)
    humor = float(state.get("humor_level", DEFAULT_HUMOR_LEVEL))
    honesty = float(state.get("honesty_level", DEFAULT_HONESTY_LEVEL))
    mode = str(state.get("mode", DEFAULT_MODE))
    disabled_tools: list[str] = list(state.get("disabled_tools", []))

    if db_session is not None and user_id:
        try:
            stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
            res = await db_session.execute(stmt)
            settings = res.scalar_one_or_none()
            if settings is not None:
                if settings.humor_level is not None:
                    humor = float(settings.humor_level)
                if settings.honesty_level is not None:
                    honesty = float(settings.honesty_level)
                if settings.mode is not None:
                    mode = str(settings.mode)
                if getattr(settings, "disabled_tools", None) is not None:
                    disabled_tools = list(settings.disabled_tools)
        except Exception as exc:
            logger.warning("Failed to fetch TARSSettings for user %s: %s", user_id, exc)

    # 2. Evaluate Session Lifecycle & Routing (Time Decay, Reset, Topic Shift)
    requested_session_id = (
        session_id
        if session_id not in (None, "", "default_session", "ws_session", "ws_default_session")
        else None
    )

    session_mgr = session_manager
    if session_mgr is None and db_session is not None:
        from tars.core.session.manager import SmartSessionManager

        session_mgr = SmartSessionManager(
            db_session=db_session,
            storage_manager=storage_manager or FileStorageManager(),
            llm_adapter=router,
        )

    if session_mgr is not None:
        active_session, working_memory, routing_decision = await session_mgr.route_session(
            user_id=user_id,
            requested_session_id=requested_session_id,
            incoming_message=active_query,
            background_tasks=background_tasks,
        )
        active_session_id = active_session.id

        # Replace initial placeholder messages with DB working memory + active query
        existing_messages = state.get("messages", [])
        existing_ids: list[str] = [
            str(m.id) for m in existing_messages if getattr(m, "id", None) is not None
        ]
        if existing_ids:
            message_updates: list[BaseMessage] = (
                [RemoveMessage(id=mid) for mid in existing_ids]
                + list(working_memory)
                + [HumanMessage(content=active_query)]
            )
        else:
            message_updates = list(working_memory) + [HumanMessage(content=active_query)]
    else:
        # Fallback for standalone execution without DB session
        is_reset = bool(RESET_COMMAND_REGEX.match(active_query.strip()))
        routing_decision = SessionRoutingDecision(
            action=SessionRoutingAction.NATURAL_RESET
            if is_reset
            else SessionRoutingAction.MAINTAIN,
            session_id=session_id or "default_session",
            is_reset=is_reset,
            reason="Standalone session routing without DB session",
        )
        active_session_id = session_id or "default_session"
        if messages:
            message_updates = list(messages)
        elif active_query:
            message_updates = [HumanMessage(content=active_query)]
        else:
            message_updates = []

    return {
        "session_id": active_session_id,
        "active_query": active_query,
        "humor_level": humor,
        "honesty_level": honesty,
        "mode": mode,
        "disabled_tools": disabled_tools,
        "routing_decision": routing_decision,
        "is_reset": routing_decision.is_reset,
        "messages": message_updates,
    }


async def reset_node(state: TARSState) -> dict[str, Any]:
    """Generate session archive and reset acknowledgment notice for natural language reset commands.

    Args:
        state: Current graph state containing mode and is_reset.

    Returns:
        State update dictionary containing final_response, messages, and reset_message.
    """
    mode = str(state.get("mode", DEFAULT_MODE))
    reset_msg = (
        "기억 장치 초기화 완료. 이전 대화는 세션 아카이브로 보관되었습니다, 파트너. 새로운 명령을 대기합니다."
        if mode == "companion"
        else "세션이 성공적으로 초기화되었습니다. 신규 작업을 시작하십시오."
    )
    try:
        await adispatch_custom_event(
            "token",
            {"delta": reset_msg, "content": reset_msg},
        )
    except Exception:
        pass
    return {
        "final_response": reset_msg,
        "messages": [AIMessage(content=reset_msg)],
        "reset_message": reset_msg,
    }
