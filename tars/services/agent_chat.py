"""Agent Chat Service orchestrating smart session lifecycle, OKF knowledge slicing,
ReAct tool calling, real-time token streaming, and continuous self-evolving knowledge extraction.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import BackgroundTasks
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter
from tars.core.session.manager import SmartSessionManager
from tars.db.models import TARSSettings
from tars.db.session import get_session_factory
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.slicer.models import SlicerProfile
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.services.agent_chat")

_background_ws_tasks: set[asyncio.Task[None]] = set()


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
    except BaseException as exc:
        logger.debug("Background knowledge extraction ended for user %s: %s", user_id, exc)
    finally:
        if db is not None:
            try:
                await db.close()
            except BaseException:
                pass


from tars.orchestrator.events import AgentStreamEvent


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
        self.slicer = slicer or DynamicSlicerEngine(storage_manager=storage_manager, db_session=db_session)

    async def stream_chat(
        self,
        user_id: str,
        message: str,
        session_id: str | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Execute full agent turn with session routing, dynamic slicing, ReAct tools, and token streaming."""
        # 1. Fetch user persona parameters
        stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
        res = await self.db.execute(stmt)
        settings = res.scalar_one_or_none()

        humor = float(settings.humor_level) if settings else 0.90
        honesty = float(settings.honesty_level) if settings else 0.95
        mode = str(settings.mode) if settings else "companion"

        # 2. Evaluate Session Lifecycle & Routing (Time Decay, Reset, Topic Shift)
        session_mgr = SmartSessionManager(
            db_session=self.db,
            storage_manager=self.storage,
            llm_adapter=self.router,
        )
        active_session, working_memory, routing_decision = await session_mgr.route_session(
            user_id=user_id,
            requested_session_id=session_id if session_id not in (None, "default_session", "ws_session", "ws_default_session") else None,
            incoming_message=message,
            background_tasks=background_tasks,
        )

        # 3. Handle Natural Language Reset Command
        if routing_decision.is_reset:
            reset_msg = (
                "기억 장치 초기화 완료. 이전 대화는 세션 아카이브로 보관되었습니다, 파트너. 새로운 명령을 대기합니다."
                if mode == "companion"
                else "세션이 성공적으로 초기화되었습니다. 신규 작업을 시작하십시오."
            )
            yield AgentStreamEvent(type="stream_start", session_id=active_session.id)
            yield AgentStreamEvent(type="token", delta=reset_msg, content=reset_msg)
            yield AgentStreamEvent(type="stream_end", session_id=active_session.id, content=reset_msg)
            yield AgentStreamEvent(type="done")

            await session_mgr.record_turn(
                session_id=active_session.id,
                user_id=user_id,
                user_content=message,
                assistant_content=reset_msg,
            )
            return

        # 4. Sliced OKF Knowledge Context (5-Factor Dynamic Slicing)
        relevant_wikis = await self.slicer.slice_context(
            user_id=user_id,
            query=message,
            context_messages=working_memory,
            profile=SlicerProfile.CHAT,
        )

        # 5. Compose System Prompt
        system_prompt = self.persona_mgr.build_system_prompt(
            humor_level=humor,
            honesty_level=honesty,
            mode=mode,
            context_docs=relevant_wikis,
        )

        # 6. Begin Turn Streaming
        yield AgentStreamEvent(type="stream_start", session_id=active_session.id)

        messages: list[BaseMessage] = list(working_memory) + [HumanMessage(content=message)]
        tools_decl = self.tool_registry.export_gemini_declarations() if self.tool_registry else []
        tools_used: list[str] = []
        accumulated_chunks: list[str] = []

        try:
            # Check if tools are available for structured ReAct execution
            if tools_decl and hasattr(self.router, "route_and_generate_response"):
                first_resp = await self.router.route_and_generate_response(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools_decl,
                    user_facing=True,
                )

                # ReAct Tool Calling Loop
                if first_resp.tool_calls:
                    iteration = 0
                    max_iterations = 3
                    current_messages = list(messages)
                    current_resp = first_resp

                    while current_resp.tool_calls and iteration < max_iterations:
                        iteration += 1
                        for tc in current_resp.tool_calls:
                            tools_used.append(tc.name)
                            yield AgentStreamEvent(
                                type="tool_start",
                                tool=tc.name,
                                call_id=tc.id,
                                args=tc.arguments,
                            )

                            try:
                                tool_result = await self.tool_registry.execute_tool(tc.name, tc.arguments)
                                yield AgentStreamEvent(
                                    type="tool_result",
                                    tool=tc.name,
                                    call_id=tc.id,
                                    status="success",
                                    result=tool_result,
                                )
                                result_str = json.dumps(tool_result, ensure_ascii=False) if not isinstance(tool_result, str) else tool_result
                            except Exception as tool_err:
                                err_msg = str(tool_err)
                                logger.warning("Tool %s execution failed: %s", tc.name, err_msg)
                                yield AgentStreamEvent(
                                    type="tool_result",
                                    tool=tc.name,
                                    call_id=tc.id,
                                    status="error",
                                    error=err_msg,
                                )
                                result_str = json.dumps({"status": "error", "error": err_msg}, ensure_ascii=False)

                            # Append tool response context
                            current_messages.append(AIMessage(content=current_resp.content or f"Calling tool {tc.name}"))
                            current_messages.append(HumanMessage(content=f"[Tool {tc.name} Result]: {result_str}"))

                        # Next reasoning turn with tool results
                        current_resp = await self.router.route_and_generate_response(
                            messages=current_messages,
                            system_prompt=system_prompt,
                            tools=tools_decl,
                            user_facing=True,
                        )

                    # Stream final synthesized response
                    final_text = current_resp.content
                    accumulated_chunks.append(final_text)
                    yield AgentStreamEvent(type="token", delta=final_text, content=final_text)

                else:
                    # Direct streaming for fast causal/non-tool reply
                    async for token in self.router.route_and_stream(
                        messages=messages,
                        system_prompt=system_prompt,
                        tools=tools_decl,
                        user_facing=True,
                    ):
                        accumulated_chunks.append(token)
                        yield AgentStreamEvent(type="token", delta=token, content=token)

            else:
                # Direct streaming without tool registry
                async for token in self.router.route_and_stream(
                    messages=messages,
                    system_prompt=system_prompt,
                    user_facing=True,
                ):
                    accumulated_chunks.append(token)
                    yield AgentStreamEvent(type="token", delta=token, content=token)

        except Exception as stream_err:
            logger.error("Error during agent stream execution: %s", stream_err, exc_info=True)
            yield AgentStreamEvent(type="error", error=str(stream_err), content=str(stream_err))
            return

        full_text = "".join(accumulated_chunks)

        # 7. Record dialogue turn in DB before ending stream
        try:
            await session_mgr.record_turn(
                session_id=active_session.id,
                user_id=user_id,
                user_content=message,
                assistant_content=full_text,
            )
        except Exception as rec_err:
            logger.error("Failed to record turn in DB: %s", rec_err, exc_info=True)

        # 8. Trigger background knowledge extraction for continuous self-evolution
        turns: list[BaseMessage] = [
            HumanMessage(content=message),
            AIMessage(content=full_text),
        ]


        # Support backward-compatible test patching via tars.api.routers.chat._execute_background_knowledge_extraction
        extract_fn = execute_background_knowledge_extraction
        try:
            import tars.api.routers.chat as chat_router_mod
            if hasattr(chat_router_mod, "_execute_background_knowledge_extraction"):
                extract_fn = chat_router_mod._execute_background_knowledge_extraction
        except Exception:
            pass

        if background_tasks is not None:
            background_tasks.add_task(
                extract_fn,
                user_id=user_id,
                conversation_turns=turns,
                storage=self.storage,
                llm_adapter=self.router,
            )
        else:
            try:
                coro_or_res = extract_fn(
                    user_id=user_id,
                    conversation_turns=turns,
                    storage=self.storage,
                    llm_adapter=self.router,
                )
                if asyncio.iscoroutine(coro_or_res):
                    ws_task = asyncio.create_task(coro_or_res)
                    _background_ws_tasks.add(ws_task)
                    ws_task.add_done_callback(_background_ws_tasks.discard)
            except Exception as bg_err:
                logger.warning("Failed to dispatch background knowledge extraction: %s", bg_err)

        # 9. Yield stream completion frames
        yield AgentStreamEvent(
            type="stream_end",
            session_id=active_session.id,
            content=full_text,
            tools_used=tools_used,
        )
        yield AgentStreamEvent(type="done")




__all__ = [
    "AgentChatService",
    "AgentStreamEvent",
    "execute_background_knowledge_extraction",
]
