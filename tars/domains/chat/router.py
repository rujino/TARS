"""Chat Streaming REST (SSE), WebSocket real-time communication, and Proactive Greeting routers.

Thin Controller pattern: Delegates orchestration and session workflows to AgentChatService and ProactiveGreetingService.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from tars.api.dependencies import (
    get_agent_chat_service,
    get_current_user,
    get_db_session,
    get_proactive_greeting_service,
    get_storage_manager,
    get_tool_registry,
)
from tars.core.config import get_settings
from tars.core.database import get_session_factory
from tars.core.security import decode_access_token, validate_and_consume_ws_ticket
from tars.domains.auth.models import User
from tars.domains.chat.models import ChatMessage, ChatSession
from tars.domains.chat.schemas import (
    ChatMessageResponse,
    ChatSessionDeleteResponse,
    ChatSessionItem,
    ChatSessionListResponse,
    ChatStreamRequest,
    GreetingResponse,
    compute_date_group,
)
from tars.domains.chat.services.agent_chat import AgentChatService
from tars.domains.chat.services.greeting import ProactiveGreetingService
from tars.domains.knowledge.storage.manager import FileStorageManager
from tars.domains.tools.registry import ToolRegistry
from tars.runtime.turn_lock import (
    HybridSessionTurnLock,
    LockContentionError,
    TurnState,
    get_redis_client,
)

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
# Session History & Timeline REST Endpoints (Milestone 3)
# ============================================================================


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="List chat sessions ordered by last_active_at with date grouping metadata",
)
async def list_chat_sessions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    timezone: str = Query(default="Asia/Seoul", description="Client IANA timezone"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionListResponse:
    """Query current user's sessions from ChatSession ordered by last_active_at DESC with date grouping."""
    count_stmt = (
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == current_user.id)
    )
    total_res = await db.execute(count_stmt)
    total = total_res.scalar_one()

    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(desc(ChatSession.last_active_at))
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    sessions_orm = res.scalars().all()

    sess_ids = [s.id for s in sessions_orm]
    counts_map: dict[str, int] = {}
    if sess_ids:
        msg_count_stmt = (
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_(sess_ids))
            .group_by(ChatMessage.session_id)
        )
        msg_counts = await db.execute(msg_count_stmt)
        counts_map = {str(row[0]): int(row[1]) for row in msg_counts.all()}

    items: list[ChatSessionItem] = []
    groups: dict[str, list[ChatSessionItem]] = {
        "Today": [],
        "Yesterday": [],
        "Past 7 days": [],
        "Past 30 days": [],
        "Older": [],
    }

    for s in sessions_orm:
        group_name = compute_date_group(s.last_active_at, timezone)
        item = ChatSessionItem(
            id=s.id,
            user_id=s.user_id,
            title=s.title,
            status=s.status,
            bridge_summary=s.bridge_summary,
            parent_session_id=s.parent_session_id,
            last_active_at=s.last_active_at,
            created_at=s.created_at,
            updated_at=s.updated_at,
            date_group=group_name,
            message_count=counts_map.get(s.id, 0),
        )
        items.append(item)
        if group_name in groups:
            groups[group_name].append(item)
        else:
            groups["Older"].append(item)

    return ChatSessionListResponse(
        sessions=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items) < total),
        groups=groups,
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
    summary="Restore all message turns for a chat session in chronological order",
)
async def get_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[ChatMessageResponse]:
    """Query ChatMessage for session ordered by created_at ASC with tenant isolation."""
    sess_stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    )
    sess_res = await db.execute(sess_stmt)
    session = sess_res.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat session '{session_id}' not found.",
        )

    msg_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at.asc())
    )
    msg_res = await db.execute(msg_stmt)
    messages = msg_res.scalars().all()

    return [
        ChatMessageResponse(
            id=m.id,
            session_id=m.session_id,
            user_id=m.user_id,
            role=m.role,
            content=m.content,
            tokens=m.tokens,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.delete(
    "/sessions/{session_id}",
    response_model=ChatSessionDeleteResponse,
    summary="Delete chat session and cascade delete all message turns",
)
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionDeleteResponse:
    """Delete session by id and user_id. Cascade delete messages."""
    sess_stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    )
    sess_res = await db.execute(sess_stmt)
    session = sess_res.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat session '{session_id}' not found.",
        )

    await db.delete(session)
    await db.commit()
    return ChatSessionDeleteResponse(success=True, session_id=session_id)


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


_ACTIVE_SESSION_LOCKS: dict[str, HybridSessionTurnLock] = {}


def get_session_turn_lock(
    sess_id: str,
    settings: Any | None = None,
    redis_client: Any | None = None,
) -> HybridSessionTurnLock:
    """Thread/task safe accessor returning shared HybridSessionTurnLock instance per session."""
    if settings is None:
        settings = get_settings()
    if redis_client is None:
        redis_client = get_redis_client()

    if sess_id not in _ACTIVE_SESSION_LOCKS:
        _ACTIVE_SESSION_LOCKS[sess_id] = HybridSessionTurnLock(
            session_id=sess_id,
            pod_id=settings.pod_id,
            redis_client=redis_client,
            watchdog_ttl_ms=settings.redis_watchdog_ttl_ms,
            heartbeat_interval=settings.redis_heartbeat_interval_seconds,
        )
    else:
        if redis_client is not None and _ACTIVE_SESSION_LOCKS[sess_id].redis != redis_client:
            _ACTIVE_SESSION_LOCKS[sess_id].redis = redis_client
    return _ACTIVE_SESSION_LOCKS[sess_id]


async def _handle_ws_chat_session(
    websocket: WebSocket,
    user_id: str,
    storage: FileStorageManager,
    tool_registry: ToolRegistry,
) -> None:
    """Run full WebSocket conversational session loop with concurrent reader and dispatcher coroutines."""
    await websocket.accept()
    logger.info("WebSocket connected for user %s", user_id)

    session_factory = get_session_factory()
    settings = get_settings()
    redis_client = get_redis_client()

    current_acquired_lock: list[HybridSessionTurnLock | None] = [None]

    def get_lock(sess_id: str) -> HybridSessionTurnLock:
        return get_session_turn_lock(sess_id, settings, redis_client)

    inbound_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    active_stream_task: asyncio.Task[None] | None = None
    active_bg_tasks: set[asyncio.Task[Any]] = set()
    last_session_id: list[str] = ["default_session"]

    async def reader() -> None:
        nonlocal active_stream_task
        while True:
            try:
                raw_data = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected normally by client in reader")
                await inbound_queue.put(None)
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
            sess_id = data.get("session_id") or last_session_id[0]
            lock = get_lock(sess_id)

            if frame_type == "user_barge_in":
                logger.info(
                    "user_barge_in received for session %s; triggering 0ms barge-in", sess_id
                )
                await lock.trigger_barge_in()
                for bg_t in list(active_bg_tasks):
                    if not bg_t.done():
                        bg_t.cancel()
                active_bg_tasks.clear()
                if active_stream_task and not active_stream_task.done():
                    active_stream_task.cancel()
                try:
                    await websocket.send_json(
                        {
                            "type": "stream_abort",
                            "session_id": sess_id,
                            "turn_epoch": lock.local_epoch,
                            "reason": "barge_in",
                        }
                    )
                except Exception:
                    pass
                continue

            elif frame_type == "user_typing":
                try:
                    await websocket.send_json(
                        {
                            "type": "typing_ack",
                            "session_id": sess_id,
                            "status": data.get("status", "active"),
                        }
                    )
                except Exception:
                    pass
                continue

            elif frame_type == "chat_message":
                user_content = data.get("content", "")
                if not user_content:
                    logger.warning("Empty chat_message content from user %s", user_id)
                    continue
                logger.info(
                    "WS received chat_message from user %s, sess=%s, len=%d",
                    user_id,
                    sess_id,
                    len(user_content),
                )
                last_session_id[0] = sess_id
                # If an active stream is ongoing, a new user message interrupts it
                if active_stream_task and not active_stream_task.done():
                    logger.info("New message arrived during active stream; triggering barge-in")
                    await lock.trigger_barge_in()
                    for bg_t in list(active_bg_tasks):
                        if not bg_t.done():
                            bg_t.cancel()
                    active_bg_tasks.clear()
                    active_stream_task.cancel()

                await inbound_queue.put(data)

    async def dispatcher() -> None:
        nonlocal active_stream_task
        while True:
            msg = await inbound_queue.get()
            if msg is None:
                # Reader signaled termination
                break

            requested_session_id = msg.get("session_id") or "default_session"
            user_content = msg.get("content", "")
            client_timezone = msg.get("timezone", "Asia/Seoul")
            message_id = msg.get("message_id") or str(uuid.uuid4())

            logger.info(
                "WS dispatcher processing message for session %s, user %s, mid %s",
                requested_session_id,
                user_id,
                message_id,
            )
            lock = get_lock(requested_session_id)

            try:
                turn_epoch = await lock.acquire_turn(speaker="assistant")
                current_acquired_lock[0] = lock
                logger.info(
                    "WS acquired turn lock for session %s (epoch %d)",
                    requested_session_id,
                    turn_epoch,
                )
            except LockContentionError as e:
                logger.warning("WS Lock contention for session %s: %s", requested_session_id, e)
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Lock contention error: {e}",
                    }
                )
                continue

            # 1. Emit Vera read receipt (~0.05s, unread_count=1)
            await asyncio.sleep(0.05)
            if (
                lock.local_epoch == turn_epoch
                and not lock.is_aborted()
                and websocket.client_state == WebSocketState.CONNECTED
            ):
                await websocket.send_json(
                    {
                        "type": "read_receipt",
                        "message_id": message_id,
                        "reader": "vera",
                        "unread_count": 1,
                        "session_id": requested_session_id,
                    }
                )

            # 2. Spawn Miu read receipt background task (0.3s - 0.45s jitter, unread_count=0)
            miu_receipt_done = asyncio.Event()

            async def _emit_miu_receipt(mid: str, sid: str, epoch: int) -> None:
                try:
                    jitter = random.uniform(0.3, 0.45)
                    await asyncio.sleep(jitter)
                    if (
                        lock.local_epoch == epoch
                        and not lock.is_aborted()
                        and websocket.client_state == WebSocketState.CONNECTED
                    ):
                        await websocket.send_json(
                            {
                                "type": "read_receipt",
                                "message_id": mid,
                                "reader": "miu",
                                "unread_count": 0,
                                "session_id": sid,
                            }
                        )
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.debug("Failed to emit Miu read receipt: %s", exc)
                finally:
                    miu_receipt_done.set()

            miu_task = asyncio.create_task(
                _emit_miu_receipt(message_id, requested_session_id, turn_epoch)
            )
            active_bg_tasks.add(miu_task)
            miu_task.add_done_callback(active_bg_tasks.discard)

            async def run_stream(epoch: int) -> None:
                typing_active = False
                typing_emitted = False
                try:
                    async with session_factory() as db:
                        agent_service = AgentChatService(
                            db_session=db,
                            storage_manager=storage,
                            tool_registry=tool_registry,
                        )
                        token_count = 0
                        async for event in agent_service.stream_chat(
                            user_id=user_id,
                            message=user_content,
                            session_id=requested_session_id,
                            client_timezone=client_timezone,
                            turn_epoch=epoch,
                        ):
                            if websocket.client_state == WebSocketState.DISCONNECTED:
                                logger.info(
                                    "Client disconnected from WebSocket during turn; terminating execution."
                                )
                                break

                            # 0ms Packet drop guard:
                            event_epoch = getattr(event, "turn_epoch", None)
                            if event_epoch is not None and event_epoch != lock.local_epoch:
                                logger.info(
                                    "0ms packet drop guard: event epoch %d != local_epoch %d",
                                    event_epoch,
                                    lock.local_epoch,
                                )
                                continue

                            if lock.local_epoch != epoch or lock.is_aborted():
                                logger.info(
                                    "0ms packet drop guard: discarding chunk with epoch %d != local_epoch %d",
                                    epoch,
                                    lock.local_epoch,
                                )
                                break

                            # Typing indicator triggers:
                            # 1) When secondary speaker prefetch triggers or during primary streaming:
                            if not typing_emitted and (event.type in ("stream_start", "token")):
                                typing_emitted = True
                                typing_active = True
                                await websocket.send_json(
                                    {
                                        "type": "typing_indicator",
                                        "sender": "miu",
                                        "status": "active",
                                        "label": "🐾 미우가 발을 동동 구르며 타자 치는 중...",
                                        "session_id": requested_session_id,
                                        "turn_epoch": epoch,
                                    }
                                )

                            # 2) When secondary speaker begins emitting tokens:
                            if typing_active and event.type == "token" and event.speaker == "miu":
                                await websocket.send_json(
                                    {
                                        "type": "typing_indicator",
                                        "sender": "miu",
                                        "status": "inactive",
                                        "session_id": requested_session_id,
                                        "turn_epoch": epoch,
                                    }
                                )
                                typing_active = False

                            if event.type != "done":
                                ws_dict = event.to_ws_dict()
                                # Tag streaming chunks with monotonic turn_epoch and session_id
                                ws_dict["turn_epoch"] = epoch
                                ws_dict["session_id"] = requested_session_id

                                if event.type == "stream_end":
                                    # Deactivate typing indicator if still active
                                    if typing_active:
                                        try:
                                            await websocket.send_json(
                                                {
                                                    "type": "typing_indicator",
                                                    "sender": "miu",
                                                    "status": "inactive",
                                                    "session_id": requested_session_id,
                                                    "turn_epoch": epoch,
                                                }
                                            )
                                        except Exception:
                                            pass
                                        typing_active = False

                                    # Ensure Miu has read before concluding the turn with stream_end
                                    if not miu_task.done():
                                        try:
                                            await asyncio.wait_for(
                                                miu_receipt_done.wait(), timeout=1.0
                                            )
                                        except (TimeoutError, asyncio.TimeoutError):
                                            pass

                                await websocket.send_json(ws_dict)

                                if event.type == "token":
                                    token_count += 1
                                elif event.type == "stream_end":
                                    logger.info(
                                        "WS turn completed: sent stream_end (%d tokens streamed)",
                                        token_count,
                                    )

                except asyncio.CancelledError:
                    logger.info("Streaming task cancelled cleanly")
                    raise
                except Exception as exc:
                    logger.error("Unexpected error in stream_chat: %s", exc, exc_info=True)
                    try:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": f"Server execution error: {exc}",
                                "turn_epoch": epoch,
                            }
                        )
                    except Exception:
                        pass
                finally:
                    if typing_active:
                        try:
                            await websocket.send_json(
                                {
                                    "type": "typing_indicator",
                                    "sender": "miu",
                                    "status": "inactive",
                                    "session_id": requested_session_id,
                                    "turn_epoch": epoch,
                                }
                            )
                        except Exception:
                            pass
                        typing_active = False
                    current_acquired_lock[0] = None
                    await lock.release_turn()

            active_stream_task = asyncio.create_task(run_stream(turn_epoch))
            lock.active_task = active_stream_task
            try:
                await active_stream_task
            except asyncio.CancelledError:
                pass
            finally:
                active_stream_task = None

    try:
        reader_task = asyncio.create_task(reader())
        dispatcher_task = asyncio.create_task(dispatcher())
        done, pending = await asyncio.wait(
            [reader_task, dispatcher_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
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
        for t in list(active_bg_tasks):
            if not t.done():
                t.cancel()
        active_bg_tasks.clear()
        active_lock = current_acquired_lock[0]
        if active_lock and active_lock.state != TurnState.IDLE:
            try:
                await active_lock.release_turn()
            except Exception:
                pass
        current_acquired_lock[0] = None
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


__all__ = ["router", "_ACTIVE_SESSION_LOCKS", "get_session_turn_lock"]
