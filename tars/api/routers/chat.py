"""Chat Streaming REST (SSE), WebSocket real-time communication, and Proactive Greeting routers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.base import BaseLLMAdapter
from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter
from tars.api.dependencies import (
    get_current_user,
    get_db_session,
    get_storage_manager,
    get_tool_registry,
)
from tars.api.schemas import (
    ChatStreamRequest,
    GreetingResponse,
)
from tars.core.security import decode_access_token
from tars.core.session.manager import SmartSessionManager
from tars.db.models import TARSSettings, User
from tars.db.session import get_session_factory
from tars.extractor.worker import SelfEvolvingKnowledgeWorker
from tars.persona.prompts import TARSPersonaManager
from tars.services.greeting import ProactiveGreetingService
from tars.slicer.engine import DynamicSlicerEngine
from tars.slicer.models import SlicerProfile
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.routers.chat")
router = APIRouter(prefix="/chat", tags=["Chat & Streaming"])


def _get_default_router() -> HybridLLMRouter:
    """Create default HybridLLMRouter with Gemini and local SLM adapters."""
    gemini = GeminiAdapter()
    slm = LlamaCppAdapter()
    return HybridLLMRouter(gemini_adapter=gemini, slm_adapter=slm)


_background_ws_tasks: set[asyncio.Task[None]] = set()


async def _execute_background_knowledge_extraction(
    user_id: str,
    conversation_turns: list[BaseMessage],
    storage: FileStorageManager,
    llm_adapter: BaseLLMAdapter | HybridLLMRouter | None = None,
) -> None:
    """Background task executing knowledge extraction and atomic DB/storage reconciliation."""
    if not user_id or not conversation_turns:
        return

    db = None
    try:
        session_factory = get_session_factory()
        db = session_factory()
        active_llm = llm_adapter or _get_default_router()
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
                "Background knowledge extraction succeeded for user %s: extracted %d documents",
                user_id,
                len(extracted_docs),
            )
    except BaseException as exc:
        logger.debug(
            "Background knowledge extraction ended for user %s: %s",
            user_id,
            exc,
        )
    finally:
        if db is not None:
            try:
                await db.close()
            except BaseException:
                pass


@router.get(
    "/greeting",
    response_model=GreetingResponse,
    summary="Fetch proactive situational greeting upon app startup or foreground entry",
)
async def get_proactive_greeting(
    timezone: str = Query(default="Asia/Seoul", description="Client IANA timezone"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorageManager = Depends(get_storage_manager),
) -> GreetingResponse:
    """Generate a 5-factor proactive, witty 1-2 sentence opening greeting in Korean."""
    llm_router = _get_default_router()
    greeting_service = ProactiveGreetingService(
        db_session=db,
        storage_manager=storage,
        llm_adapter=llm_router,
    )
    return await greeting_service.generate_greeting(
        user_id=current_user.id,
        client_timezone=timezone,
    )


@router.post(
    "/stream",
    summary="Stream real-time tokens via Server-Sent Events (SSE)",
)
async def chat_sse_stream(
    payload: ChatStreamRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorageManager = Depends(get_storage_manager),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> StreamingResponse:
    """Stream model response tokens using standard SSE protocol with Smart Session routing."""
    # 1. Retrieve user persona settings
    stmt = select(TARSSettings).where(TARSSettings.user_id == current_user.id)
    res = await db.execute(stmt)
    settings = res.scalar_one_or_none()

    humor = float(settings.humor_level) if settings else 0.90
    honesty = float(settings.honesty_level) if settings else 0.95
    mode = str(settings.mode) if settings else "companion"

    llm_router = _get_default_router()

    # 2. Evaluate Session Lifecycle & Routing (Time Decay, Reset, Topic Shift)
    session_mgr = SmartSessionManager(
        db_session=db,
        storage_manager=storage,
        llm_adapter=llm_router,
    )
    active_session, working_memory, routing_decision = await session_mgr.route_session(
        user_id=current_user.id,
        requested_session_id=payload.session_id
        if payload.session_id != "default_session"
        else None,
        incoming_message=payload.message,
        background_tasks=background_tasks,
    )

    # 3. Handle Natural Language Reset Command
    if routing_decision.is_reset:
        reset_msg = (
            "기억 장치 초기화 완료. 이전 대화는 세션 아카이브로 보관되었습니다, 파트너. 새로운 명령을 대기합니다."
            if mode == "companion"
            else "세션이 성공적으로 초기화되었습니다. 신규 작업을 시작하십시오."
        )

        async def sse_reset_generator() -> AsyncIterator[str]:
            start_payload = json.dumps({"session_id": active_session.id}, ensure_ascii=False)
            yield f"event: stream_start\ndata: {start_payload}\n\n"
            token_payload = json.dumps(
                {"content": reset_msg, "delta": reset_msg}, ensure_ascii=False
            )
            yield f"event: token\ndata: {token_payload}\n\n"
            end_payload = json.dumps({"content": reset_msg}, ensure_ascii=False)
            yield f"event: stream_end\ndata: {end_payload}\n\n"
            yield "event: done\ndata: [DONE]\n\n"

            # Record reset turn
            await session_mgr.record_turn(
                session_id=active_session.id,
                user_id=current_user.id,
                user_content=payload.message,
                assistant_content=reset_msg,
            )

        return StreamingResponse(
            sse_reset_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 4. Sliced OKF Knowledge Context
    slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db)
    relevant_wikis = await slicer.slice_context(
        user_id=current_user.id,
        query=payload.message,
        context_messages=working_memory,
        profile=SlicerProfile.CHAT,
    )

    # 5. Compose System Prompt
    persona_mgr = TARSPersonaManager()
    system_prompt = persona_mgr.build_system_prompt(
        humor_level=humor,
        honesty_level=honesty,
        mode=mode,
        context_docs=relevant_wikis,
    )

    # 6. Stream Model Response
    async def sse_event_generator() -> AsyncIterator[str]:
        # Emit stream_start event
        start_payload = json.dumps({"session_id": active_session.id}, ensure_ascii=False)
        yield f"event: stream_start\ndata: {start_payload}\n\n"

        accumulated_chunks: list[str] = []
        messages: list[BaseMessage] = list(working_memory) + [HumanMessage(content=payload.message)]

        try:
            tools_decl = tool_registry.export_gemini_declarations() if tool_registry else None
            async for token in llm_router.route_and_stream(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools_decl,
            ):
                accumulated_chunks.append(token)
                token_payload = json.dumps({"content": token, "delta": token}, ensure_ascii=False)
                yield f"event: token\ndata: {token_payload}\n\n"
        except Exception as stream_err:
            logger.error("Error during SSE streaming: %s", stream_err, exc_info=True)
            err_payload = json.dumps({"error": str(stream_err)}, ensure_ascii=False)
            yield f"event: error\ndata: {err_payload}\n\n"
            return

        full_text = "".join(accumulated_chunks)

        # Emit stream_end event
        end_payload = json.dumps({"content": full_text}, ensure_ascii=False)
        yield f"event: stream_end\ndata: {end_payload}\n\n"

        # Emit done event
        yield "event: done\ndata: [DONE]\n\n"

        # Record conversation turn in DB
        try:
            await session_mgr.record_turn(
                session_id=active_session.id,
                user_id=current_user.id,
                user_content=payload.message,
                assistant_content=full_text,
            )
        except Exception as rec_err:
            logger.error("Failed to record conversation turn: %s", rec_err, exc_info=True)

        # Launch background knowledge extraction for continuous self-evolution
        turns: list[BaseMessage] = [
            HumanMessage(content=payload.message),
            AIMessage(content=full_text),
        ]
        background_tasks.add_task(
            _execute_background_knowledge_extraction,
            user_id=current_user.id,
            conversation_turns=turns,
            storage=storage,
            llm_adapter=llm_router,
        )

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws")
async def chat_websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    storage: FileStorageManager = Depends(get_storage_manager),
) -> None:
    """Bidirectional WebSocket streaming endpoint with token authentication and Smart Session routing."""
    # 1. Validate JWT Token
    if not token:
        logger.warning("WebSocket rejected: missing token query param")
        await websocket.close(code=4001)
        return

    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        logger.warning("WebSocket rejected: invalid or expired token")
        await websocket.close(code=4001)
        return

    user_id = str(payload["sub"])

    # 2. Verify User in DB
    session_factory = get_session_factory()
    async with session_factory() as db:
        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if user is None or not user.is_active:
            logger.warning("WebSocket rejected: user not found or inactive (%s)", user_id)
            await websocket.close(code=4001)
            return

    # Accept WebSocket connection
    await websocket.accept()
    logger.info("WebSocket connected for user %s", user_id)

    llm_router = _get_default_router()

    try:
        while True:
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected normally by client")
                break

            try:
                data = json.loads(raw_data)
            except Exception:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Malformed JSON payload received",
                    }
                )
                continue

            frame_type = data.get("type", "chat_message")
            requested_session_id = data.get("session_id")
            user_content = data.get("content", "")

            if frame_type != "chat_message" or not user_content:
                continue

            async with session_factory() as db:
                # Fetch persona config
                stmt_settings = select(TARSSettings).where(TARSSettings.user_id == user_id)
                res_settings = await db.execute(stmt_settings)
                settings = res_settings.scalar_one_or_none()

                humor = float(settings.humor_level) if settings else 0.90
                honesty = float(settings.honesty_level) if settings else 0.95
                mode = str(settings.mode) if settings else "companion"

                # Route session
                session_mgr = SmartSessionManager(
                    db_session=db,
                    storage_manager=storage,
                    llm_adapter=llm_router,
                )
                active_session, working_memory, routing_decision = await session_mgr.route_session(
                    user_id=user_id,
                    requested_session_id=requested_session_id
                    if requested_session_id not in ("ws_session", "ws_default_session")
                    else None,
                    incoming_message=user_content,
                )

                # Reset command handling
                if routing_decision.is_reset:
                    reset_msg = (
                        "기억 장치 초기화 완료. 이전 대화는 세션 아카이브로 보관되었습니다, 파트너. 새로운 명령을 대기합니다."
                        if mode == "companion"
                        else "세션이 성공적으로 초기화되었습니다. 신규 작업을 시작하십시오."
                    )
                    await session_mgr.record_turn(
                        session_id=active_session.id,
                        user_id=user_id,
                        user_content=user_content,
                        assistant_content=reset_msg,
                    )
                    await websocket.send_json(
                        {
                            "type": "stream_start",
                            "session_id": active_session.id,
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "token",
                            "content": reset_msg,
                            "delta": reset_msg,
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "stream_end",
                            "session_id": active_session.id,
                            "content": reset_msg,
                        }
                    )
                    continue

                # Build system prompt
                slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db)
                relevant_wikis = await slicer.slice_context(
                    user_id=user_id,
                    query=user_content,
                    context_messages=working_memory,
                    profile=SlicerProfile.CHAT,
                )
                persona_mgr = TARSPersonaManager()
                system_prompt = persona_mgr.build_system_prompt(
                    humor_level=humor,
                    honesty_level=honesty,
                    mode=mode,
                    context_docs=relevant_wikis,
                )

                # Send stream_start frame
                await websocket.send_json(
                    {
                        "type": "stream_start",
                        "session_id": active_session.id,
                    }
                )

                accumulated_text: list[str] = []
                messages = list(working_memory) + [HumanMessage(content=user_content)]

                try:
                    async for chunk in llm_router.route_and_stream(
                        messages=messages,
                        system_prompt=system_prompt,
                    ):
                        accumulated_text.append(chunk)
                        # Send token frame
                        await websocket.send_json(
                            {
                                "type": "token",
                                "content": chunk,
                                "delta": chunk,
                            }
                        )
                except Exception as stream_err:
                    logger.error("WebSocket stream error: %s", stream_err, exc_info=True)
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": str(stream_err),
                        }
                    )
                    continue

                # Record turn in DB before ending stream frame
                full_response = "".join(accumulated_text)
                try:
                    await session_mgr.record_turn(
                        session_id=active_session.id,
                        user_id=user_id,
                        user_content=user_content,
                        assistant_content=full_response,
                    )
                except Exception as rec_err:
                    logger.error("Failed to record turn in websocket: %s", rec_err, exc_info=True)

                # Send stream_end frame
                await websocket.send_json(
                    {
                        "type": "stream_end",
                        "session_id": active_session.id,
                        "content": full_response,
                    }
                )

                # Non-blocking async background knowledge extraction
                ws_turns: list[BaseMessage] = [
                    HumanMessage(content=user_content),
                    AIMessage(content=full_response),
                ]
                ws_task = asyncio.create_task(
                    _execute_background_knowledge_extraction(
                        user_id=user_id,
                        conversation_turns=ws_turns,
                        storage=storage,
                        llm_adapter=llm_router,
                    )
                )
                _background_ws_tasks.add(ws_task)
                ws_task.add_done_callback(_background_ws_tasks.discard)

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed for user %s", user_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket exception: %s", exc, exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if _background_ws_tasks:
            pending = list(_background_ws_tasks)
            if pending:
                try:
                    await asyncio.wait(pending, timeout=0.5)
                except Exception:
                    pass


__all__ = ["router"]
