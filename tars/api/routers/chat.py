"""Chat Streaming REST (SSE), WebSocket real-time communication, and Proactive Greeting routers.

Thin Controller pattern: Delegates orchestration and session workflows to AgentChatService.
"""

from __future__ import annotations

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.adapters.gemini import GeminiAdapter
from tars.adapters.llamacpp import LlamaCppAdapter
from tars.adapters.router import HybridLLMRouter
from tars.api.dependencies import (
    get_agent_chat_service,
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
from tars.db.models import User
from tars.db.session import get_session_factory
from tars.services.agent_chat import (
    AgentChatService,
    execute_background_knowledge_extraction,
)
from tars.services.greeting import ProactiveGreetingService
from tars.storage.manager import FileStorageManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.api.routers.chat")
router = APIRouter(prefix="/chat", tags=["Chat & Streaming"])

# Compatibility alias for backward test references
_execute_background_knowledge_extraction = execute_background_knowledge_extraction


def _get_default_router() -> HybridLLMRouter:
    """Create default HybridLLMRouter with Gemini and local SLM adapters."""
    return HybridLLMRouter(gemini_adapter=GeminiAdapter(), slm_adapter=LlamaCppAdapter())


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
    agent_service: AgentChatService = Depends(get_agent_chat_service),
) -> StreamingResponse:
    """Stream model response tokens using standard SSE protocol with unified Agent ReAct pipeline."""

    async def sse_event_generator() -> AsyncIterator[str]:
        async for event in agent_service.stream_chat(
            user_id=current_user.id,
            message=payload.message,
            session_id=payload.session_id,
            background_tasks=background_tasks,
        ):
            yield event.to_sse_event()

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
    """양방향 실시간 WebSocket 대화 엔드포인트 (Thin Controller)."""
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

            # Execute turn via AgentChatService
            async with session_factory() as db:
                agent_service = AgentChatService(
                    db_session=db,
                    storage_manager=storage,
                    tool_registry=tool_registry,
                )
                async for event in agent_service.stream_chat(
                    user_id=user_id,
                    message=user_content,
                    session_id=requested_session_id,
                ):
                    if event.type != "done":
                        await websocket.send_json(event.to_ws_dict())


    except WebSocketDisconnect:
        logger.info("WebSocket connection closed for user %s", user_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket exception: %s", exc, exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        logger.debug("WebSocket handler connection cleaned up for user %s", user_id)




__all__ = ["router"]
