"""Post-processing and background task lifecycle management for TARS orchestration pipeline."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.engine.orchestrator.state import TARSState

if TYPE_CHECKING:
    from fastapi import BackgroundTasks
    from sqlalchemy.ext.asyncio import AsyncSession

    from tars.core.session.manager import SmartSessionManager
    from tars.engine.adapters.router import HybridLLMRouter

logger = logging.getLogger("tars.engine.orchestrator.nodes.postprocess")

_background_node_tasks: set[asyncio.Task[None]] = set()


async def postprocess_node(
    state: TARSState,
    session_manager: SmartSessionManager | None = None,
    db_session: AsyncSession | None = None,
    storage_manager: FileStorageManager | None = None,
    router: HybridLLMRouter | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Persist completed dialogue turn in DB and queue background knowledge extraction.

    Protects database turns from system prompt contamination: only pure HumanMessage
    and AIMessage contents are recorded.

    Args:
        state: Current graph state containing user_id, session_id, active_query, final_response.
        session_manager: Optional SmartSessionManager instance.
        db_session: Optional AsyncSession for database operations.
        storage_manager: Optional FileStorageManager instance.
        router: Optional HybridLLMRouter instance.
        background_tasks: Optional FastAPI BackgroundTasks for async execution.

    Returns:
        State update dictionary containing engine and model_name.
    """
    user_id = state.get("user_id", "")
    session_id = state.get("session_id", "")
    active_query = state.get("active_query", "")
    final_response = state.get("final_response", "")
    is_reset = bool(state.get("is_reset", False))

    session_mgr = session_manager
    if session_mgr is None and db_session is not None:
        from tars.core.session.manager import SmartSessionManager

        session_mgr = SmartSessionManager(
            db_session=db_session,
            storage_manager=storage_manager or FileStorageManager(),
            llm_adapter=router,
        )

    # 1. Persist completed turn in database
    if session_mgr is not None and user_id and session_id and active_query and final_response:
        try:
            await session_mgr.record_turn(
                session_id=session_id,
                user_id=user_id,
                user_content=active_query,
                assistant_content=final_response,
            )
        except Exception as exc:
            logger.error(
                "Failed to record turn in DB for session %s: %s", session_id, exc, exc_info=True
            )

    # 2. Queue background knowledge extraction (skip for natural reset turns)
    if not is_reset and user_id and active_query and final_response and storage_manager is not None:
        turns: list[BaseMessage] = [
            HumanMessage(content=active_query),
            AIMessage(content=final_response),
        ]

        from tars.domains.chat.services.agent_chat import (
            execute_background_knowledge_extraction,
        )

        if background_tasks is not None:
            background_tasks.add_task(
                execute_background_knowledge_extraction,
                user_id=user_id,
                conversation_turns=turns,
                storage=storage_manager,
                llm_adapter=router,
            )
        else:
            try:
                coro_or_res = execute_background_knowledge_extraction(
                    user_id=user_id,
                    conversation_turns=turns,
                    storage=storage_manager,
                    llm_adapter=router,
                )
                if asyncio.iscoroutine(coro_or_res):
                    task = asyncio.create_task(coro_or_res)
                    _background_node_tasks.add(task)
                    task.add_done_callback(_background_node_tasks.discard)
            except Exception as bg_err:
                logger.error(
                    "Failed to dispatch background knowledge extraction: %s", bg_err, exc_info=True
                )

    return {
        "engine": state.get("engine"),
        "model_name": state.get("model_name"),
    }


async def shutdown_background_tasks(timeout: float = 5.0) -> None:
    """Gracefully wait for pending background extraction tasks during server shutdown.

    Args:
        timeout: Maximum seconds to wait for active tasks before cancelling.
    """
    if not _background_node_tasks:
        return

    pending = [t for t in _background_node_tasks if not t.done()]
    if not pending:
        _background_node_tasks.clear()
        return

    logger.info(
        "Shutdown initiated: waiting for %d background task(s) to finish (timeout=%.1fs)...",
        len(pending),
        timeout,
    )
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    logger.info(
        "Background tasks shutdown: %d completed, %d timed out",
        len(done),
        len(still_pending),
    )

    for t in still_pending:
        t.cancel()

    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)

    _background_node_tasks.clear()
