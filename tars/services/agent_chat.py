"""Agent Chat Service orchestrating smart session lifecycle, OKF knowledge slicing,
ReAct tool calling, real-time token streaming, and continuous self-evolving knowledge extraction.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import BackgroundTasks
from langchain_core.messages import BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter
from tars.db.session import get_session_factory
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.orchestrator.graph import build_tars_graph
from tars.orchestrator.models import AgentStreamEvent
from tars.orchestrator.state import TARSState
from tars.orchestrator.stream_bridge import LangGraphStreamBridge
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.services.agent_chat")


async def execute_background_knowledge_extraction(
    user_id: str,
    conversation_turns: list[BaseMessage],
    storage: FileStorageManager,
    llm_adapter: BaseLLMAdapter | HybridLLMRouter | None = None,
) -> None:
    """Background worker task extracting valuable facts and synchronizing OKF docs and DB indexes."""
    if not user_id or not conversation_turns:
        return

    db = None
    try:
        session_factory = get_session_factory()
        db = session_factory()
        active_llm = llm_adapter or HybridLLMRouter(
            gemini_adapter=GeminiAdapter(),
            slm_adapter=LlamaCppAdapter(),
        )
        worker = SelfEvolvingKnowledgeWorker(
            extractor_llm=active_llm,
            storage_manager=storage,
        )
        extracted_docs = await worker.extract_and_sync(
            user_id=user_id,
            conversation_turns=conversation_turns,
            db_session=db,
        )
        if extracted_docs:
            logger.info(
                "Background knowledge extraction succeeded for user %s: %d documents extracted",
                user_id,
                len(extracted_docs),
            )
    except asyncio.CancelledError:
        logger.warning("Background knowledge extraction cancelled for user %s", user_id)
        raise
    except Exception as exc:
        logger.error(
            "Background knowledge extraction failed for user %s: %s",
            user_id,
            exc,
            exc_info=True,
        )
    finally:
        if db is not None:
            try:
                await db.close()
            except BaseException:
                pass


class AgentChatService:
    """Rich service managing conversational turn lifecycle, knowledge retrieval, and tool ReAct execution."""

    def __init__(
        self,
        db_session: AsyncSession,
        storage_manager: FileStorageManager,
        tool_registry: ToolRegistry | None = None,
        llm_router: HybridLLMRouter | None = None,
        persona_manager: TARSPersonaManager | None = None,
        slicer: DynamicSlicerEngine | None = None,
    ) -> None:
        self.db = db_session
        self.storage = storage_manager
        self.tool_registry = tool_registry
        self.router = llm_router or HybridLLMRouter(
            gemini_adapter=GeminiAdapter(),
            slm_adapter=LlamaCppAdapter(),
        )
        self.persona_mgr = persona_manager or TARSPersonaManager()
        self.slicer = slicer or DynamicSlicerEngine(
            storage_manager=storage_manager, db_session=db_session
        )

    async def stream_chat(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Execute full agent turn with session routing, dynamic slicing, ReAct tools, and token streaming."""
        graph = build_tars_graph(
            router=self.router,
            slicer=self.slicer,
            persona_manager=self.persona_mgr,
            tool_registry=self.tool_registry,
            db_session=self.db,
            storage_manager=self.storage,
            background_tasks=background_tasks,
        ).compile()

        initial_state: TARSState = {
            "user_id": user_id,
            "session_id": session_id or "",
            "active_query": message,
            "messages": [HumanMessage(content=message)],
            "iteration_count": 0,
            "tools_used": [],
        }

        async for event in LangGraphStreamBridge.stream_graph_events(
            graph=graph,
            initial_state=initial_state,
            background_tasks=background_tasks,
        ):
            yield event


__all__ = [
    "AgentChatService",
    "AgentStreamEvent",
    "execute_background_knowledge_extraction",
]
