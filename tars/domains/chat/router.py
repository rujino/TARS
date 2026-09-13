"""Chat Streaming REST (SSE), WebSocket real-time communication, and Proactive Greeting routers.

Thin Controller pattern: Delegates orchestration and session workflows to AgentChatService and ProactiveGreetingService.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.websockets import WebSocketState

from tars.api.dependencies import (
    get_agent_chat_service,
    get_current_user,
    get_proactive_greeting_service,
    get_storage_manager,
    get_tool_registry,
)
from tars.core.database import get_session_factory
from tars.core.security import decode_access_token, validate_and_consume_ws_ticket
from tars.domains.auth.models import User
from tars.domains.chat.schemas import (
    ChatStreamRequest,
    GreetingResponse,
)
from tars.domains.chat.services.agent_chat import AgentChatService
from tars.domains.chat.services.greeting import ProactiveGreetingService
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.tools.registry import ToolRegistry

logger = logging.getLogger("tars.domains.chat.router")
router = APIRouter(prefix="/chat", tags=["Chat & Streaming"])


@router.get(
    "/greeting",
    response_model=GreetingResponse,
    summary="Fetch proactive situational greeting upon app startup or foreground entry",
)
async def get_proactive_greeting(
    timezone: str = Query(default="Asia/Seoul", description="Client IANA timezone"),
    current_user: User = Depends(get_current_user),
    greeting_service: ProactiveGreetingService = Depends(get_proactive_greeting_service),
) -> GreetingResponse:
    """Generate a 5-factor proactive, witty 1-2 sentence opening greeting in Korean."""
    return await greeting_service.generate_greeting(
        user_id=current_user.id,
        client_timezone=timezone,
    )


# ============================================================================
# Streaming & Session Helpers (Thin Controller Delegation)
# ============================================================================


async def _generate_sse_stream(
    agent_service: AgentChatService,
    user_id: str,
    payload: ChatStreamRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> AsyncIterator[str]:
    """Generate SSE events from AgentChatService with heartbeat ping and disconnect termination."""
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=100)
    sentinel = object()

    async def producer() -> None:
        try:
            async for event in agent_service.stream_chat(
                user_id=user_id,
                message=payload.message,
                session_id=payload.session_id,
                client_timezone=payload.timezone,
                background_tasks=background_tasks,
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected from SSE stream; terminating graph execution")
                    break
                await queue.put(event)
        except asyncio.CancelledError:
            logger.info("Client disconnected from SSE stream; terminating graph execution")
            raise
        except Exception as exc:
            await queue.put(exc)
        finally:
            await queue.put(sentinel)

    producer_task = asyncio.create_task(producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except TimeoutError:
                if await request.is_disconnected():
                    logger.info("Client disconnected from SSE stream; terminating graph execution")
                    break
                yield ": ping\n\n"
                continue

            if item is sentinel:
                break
            if isinstance(item, Exception):
                logger.error("Error encountered in SSE stream: %s", item, exc_info=True)
                yield f"event: error\ndata: {json.dumps({'error': str(item)})}\n\n"
                break

            if await request.is_disconnected():
                logger.info("Client disconnected from SSE stream; terminating graph execution")
                break

            yield item.to_sse_event()
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except (asyncio.CancelledError, Exception):
                pass


def _create_sse_streaming_response(
    agent_service: AgentChatService,
    user_id: str,
    payload: ChatStreamRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> StreamingResponse:
    """Create a configured StreamingResponse for SSE chat streaming."""
    return StreamingResponse(
        _generate_sse_stream(
            agent_service=agent_service,
            user_id=user_id,
            payload=payload,
            background_tasks=background_tasks,
            request=request,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _authenticate_ws_connection(
    websocket: WebSocket,
    ticket: str | None = None,
    token: str | None = None,
) -> str | None:
    """Authenticate incoming WebSocket connection via header, ticket, or legacy token, and verify active user."""
    user_id: str | None = None

    # 1. Native mobile apps / HTTP clients with Authorization header
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        header_token = auth_header[7:].strip()
        payload = decode_access_token(header_token)
        if payload and "sub" in payload:
            user_id = str(payload["sub"])

    # 2. Web browser 1-time single-use ticket
    if user_id is None and ticket:
        user_id = validate_and_consume_ws_ticket(ticket)
        if not user_id:
            logger.warning("WebSocket rejected: invalid, expired, or reused ticket")
            await websocket.close(code=4001)
            return None

    # 3. Legacy query token fallback (with deprecation notice)
    if user_id is None and token:
        logger.warning(
            "WebSocket connected with deprecated '?token=' query param; migrate to ws-ticket"
        )
        payload = decode_access_token(token)
        if payload and "sub" in payload:
            user_id = str(payload["sub"])

    if not user_id:
        logger.warning("WebSocket rejected: missing valid ticket, token, or auth header")
        await websocket.close(code=4001)
        return None

    session_factory = get_session_factory()
    async with session_factory() as db:
        stmt = select(User).where(User.id == user_id)
        res = await db.execute(stmt)
        user = res.scalar_one_or_none()
        if user is None or not user.is_active:
            logger.warning("WebSocket rejected: user not found or inactive (%s)", user_id)
            await websocket.close(code=4001)
            return None

    return user_id


async def _handle_ws_chat_session(
    websocket: WebSocket,
    user_id: str,
    storage: FileStorageManager,
    tool_registry: ToolRegistry,
) -> None:
    """Run full WebSocket conversational session loop with turn handling and error resilience."""
    await websocket.accept()
    logger.info("WebSocket connected for user %s", user_id)

    session_factory = get_session_factory()
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
            client_timezone = data.get("timezone", "Asia/Seoul")

            if frame_type != "chat_message" or not user_content:
                continue

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
                    client_timezone=client_timezone,
                ):
                    if websocket.client_state == WebSocketState.DISCONNECTED:
                        logger.info(
                            "Client disconnected from WebSocket during turn; terminating execution."
                        )
                        break
                    if event.type != "done":
                        await websocket.send_json(event.to_ws_dict())

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed for user %s", user_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket exception: %s", exc, exc_info=True)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Server execution error: {exc}",
                }
            )
        except Exception:
            pass
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        logger.debug("WebSocket handler connection cleaned up for user %s", user_id)


# ============================================================================
# Routers (Thin Controllers)
# ============================================================================


@router.post(
    "/stream",
    summary="Stream real-time tokens via Server-Sent Events (SSE)",
)
async def chat_sse_stream(
    request: Request,
    payload: ChatStreamRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    agent_service: AgentChatService = Depends(get_agent_chat_service),
) -> StreamingResponse:
    """Stream model response tokens using standard SSE protocol with unified Agent ReAct pipeline."""
    return _create_sse_streaming_response(
        agent_service=agent_service,
        user_id=current_user.id,
        payload=payload,
        background_tasks=background_tasks,
        request=request,
    )


@router.websocket("/ws")
async def chat_websocket_endpoint(
    websocket: WebSocket,
    ticket: str | None = Query(default=None),
    token: str | None = Query(default=None),
    storage: FileStorageManager = Depends(get_storage_manager),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> None:
    """양방향 실시간 WebSocket 대화 엔드포인트 (Thin Controller)."""
    user_id = await _authenticate_ws_connection(websocket, ticket=ticket, token=token)
    if not user_id:
        return

    await _handle_ws_chat_session(
        websocket=websocket,
        user_id=user_id,
        storage=storage,
        tool_registry=tool_registry,
    )


__all__ = ["router"]
