"""Chat Streaming REST (SSE) and WebSocket real-time communication routers."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import (
    APIRouter,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter
from tars.api.dependencies import (
    get_current_user,
    get_db_session,
    get_storage_manager,
    get_tool_registry,
)
from tars.api.schemas import ChatStreamRequest
from tars.core.security import decode_access_token
from tars.db.models import TARSSettings, User
from tars.db.session import get_session_factory
from tars.persona.prompts import TARSPersonaManager
from tars.slicer.engine import DynamicSlicerEngine
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.routers.chat")
router = APIRouter(prefix="/chat", tags=["Chat & Streaming"])


def _get_default_router() -> HybridLLMRouter:
    """Create default HybridLLMRouter with Gemini and local SLM adapters."""
    gemini = GeminiAdapter()
    slm = LlamaCppAdapter()
    return HybridLLMRouter(gemini_adapter=gemini, slm_adapter=slm)


@router.post(
    "/stream",
    summary="Stream real-time tokens via Server-Sent Events (SSE)",
)
async def chat_sse_stream(
    payload: ChatStreamRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorageManager = Depends(get_storage_manager),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> StreamingResponse:
    """Stream model response tokens using standard SSE protocol."""
    # Retrieve user persona settings
    stmt = select(TARSSettings).where(TARSSettings.user_id == current_user.id)
    res = await db.execute(stmt)
    settings = res.scalar_one_or_none()

    humor = float(settings.humor_level) if settings else 0.90
    honesty = float(settings.honesty_level) if settings else 0.95
    mode = str(settings.mode) if settings else "companion"

    # Slice knowledge context
    slicer = DynamicSlicerEngine(storage_manager=storage, db_session=db)
    relevant_wikis = await slicer.slice_context(
        user_id=current_user.id,
        query=payload.message,
    )

    # Compose system prompt
    persona_mgr = TARSPersonaManager()
    system_prompt = persona_mgr.build_system_prompt(
        humor_level=humor,
        honesty_level=honesty,
        mode=mode,
        context_docs=relevant_wikis,
    )

    llm_router = _get_default_router()

    async def sse_event_generator() -> AsyncIterator[str]:
        # 1. Emit stream_start event
        start_payload = json.dumps({"session_id": payload.session_id})
        yield f"event: stream_start\ndata: {start_payload}\n\n"

        # 2. Stream tokens from router
        accumulated_chunks: list[str] = []
        messages = [HumanMessage(content=payload.message)]

        try:
            tools_decl = tool_registry.export_gemini_declarations() if tool_registry else None
            async for token in llm_router.route_and_stream(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools_decl,
            ):
                accumulated_chunks.append(token)
                token_payload = json.dumps({"content": token, "delta": token})
                yield f"event: token\ndata: {token_payload}\n\n"
        except Exception as stream_err:
            logger.error("Error during SSE streaming: %s", stream_err, exc_info=True)
            err_payload = json.dumps({"error": str(stream_err)})
            yield f"event: error\ndata: {err_payload}\n\n"
            return

        full_text = "".join(accumulated_chunks)

        # 3. Emit stream_end event
        end_payload = json.dumps({"content": full_text})
        yield f"event: stream_end\ndata: {end_payload}\n\n"

        # 4. Emit done event
        yield "event: done\ndata: [DONE]\n\n"

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
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> None:
    """Bidirectional WebSocket streaming endpoint with token authentication."""
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
            session_id = data.get("session_id", "ws_default_session")
            user_content = data.get("content", "")

            if frame_type != "chat_message" or not user_content:
                continue

            # Fetch persona config
            async with session_factory() as db:
                stmt_settings = select(TARSSettings).where(TARSSettings.user_id == user_id)
                res_settings = await db.execute(stmt_settings)
                settings = res_settings.scalar_one_or_none()

            humor = float(settings.humor_level) if settings else 0.90
            honesty = float(settings.honesty_level) if settings else 0.95
            mode = str(settings.mode) if settings else "companion"

            # Build system prompt
            persona_mgr = TARSPersonaManager()
            system_prompt = persona_mgr.build_system_prompt(
                humor_level=humor,
                honesty_level=honesty,
                mode=mode,
            )

            # 1. Send stream_start frame
            await websocket.send_json(
                {
                    "type": "stream_start",
                    "session_id": session_id,
                }
            )

            accumulated_text: list[str] = []
            messages = [HumanMessage(content=user_content)]

            try:
                async for chunk in llm_router.route_and_stream(
                    messages=messages,
                    system_prompt=system_prompt,
                ):
                    accumulated_text.append(chunk)
                    # 2. Send token frame
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

                accumulated_text: list[str] = []
                messages = list(working_memory) + [HumanMessage(content=user_content)]

                try:
                    tools_decl = (
                        tool_registry.export_gemini_declarations() if tool_registry else None
                    )
                    async for chunk in llm_router.route_and_stream(
                        messages=messages,
                        system_prompt=system_prompt,
                        tools=tools_decl,
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


__all__ = ["router"]
