"""Chat and Streaming Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field


def compute_date_group(last_active_at: datetime, client_tz: str = "Asia/Seoul") -> str:
    """Classify datetime into Today, Yesterday, Past 7 days, Past 30 days, or Older with client timezone support."""
    tz: tzinfo
    try:
        tz = ZoneInfo(client_tz)
    except Exception:
        tz = UTC

    local_now = datetime.now(tz)
    sess_dt = last_active_at if last_active_at.tzinfo else last_active_at.replace(tzinfo=UTC)
    local_sess = sess_dt.astimezone(tz)

    diff_days = (local_now.date() - local_sess.date()).days
    if diff_days <= 0:
        return "Today"
    elif diff_days == 1:
        return "Yesterday"
    elif diff_days <= 7:
        return "Past 7 days"
    elif diff_days <= 30:
        return "Past 30 days"
    else:
        return "Older"


class ChatStreamRequest(BaseModel):
    """Payload for initiating a real-time SSE token stream."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default="default_session", description="Conversation session ID")
    message: str = Field(..., min_length=1, description="Non-empty user query")
    timezone: str = Field(default="Asia/Seoul", description="Client IANA timezone")


class WSMessageIn(BaseModel):
    """Incoming WebSocket frame from client."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="chat_message", description="Message frame type")
    session_id: str = Field(default="ws_session", description="Dialogue session ID")
    content: str = Field(default="", description="User message content")
    timezone: str = Field(default="Asia/Seoul", description="Client IANA timezone")
    message_id: str | None = Field(default=None, description="Client-generated unique message ID")
    status: str | None = Field(default=None, description="User typing status: active | inactive")


class WSMessageOut(BaseModel):
    """Outgoing WebSocket event frame to client."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(
        ...,
        description="Event type: stream_start | token | stream_end | error | read_receipt | typing_indicator | typing_ack | stream_abort",
    )
    session_id: str | None = None
    content: str | None = None
    delta: str | None = None
    title: str | None = None
    error: str | None = None
    message_id: str | None = Field(default=None, description="Client message ID for read receipts")
    reader: str | None = Field(default=None, description="Persona reader ID (e.g. vera, miu)")
    unread_count: int | None = Field(
        default=None, description="Remaining unread counter (2 -> 1 -> 0)"
    )
    sender: str | None = Field(
        default=None, description="Typing indicator sender persona ID (e.g. miu, vera)"
    )
    status: str | None = Field(default=None, description="Typing status: active | inactive")
    label: str | None = Field(default=None, description="Human-readable typing indicator text")
    speaker: str | None = Field(
        default=None, description="Current speaker persona ID (e.g. vera, miu)"
    )
    avatar: str | None = Field(default=None, description="Speaker avatar URL or asset path")
    turn_epoch: int | None = Field(
        default=None, description="Monotonic turn epoch for concurrency arbitration"
    )
    turn_state: str | None = Field(
        default=None, description="Turn state metadata (e.g. primary, secondary)"
    )


class GreetingResponse(BaseModel):
    """Proactive greeting response payload delivered upon client launch."""

    model_config = ConfigDict(extra="ignore")

    greeting: str = Field(..., description="Witty proactive greeting text in Korean")
    session_id: str = Field(..., description="Active or newly created session ID")
    mode: str = Field(default="companion", description="Current TARS mode (companion or work)")
    idle_seconds: int = Field(
        default=0, description="Seconds elapsed since last user interaction (-1 for new user)"
    )


class SessionInfoResponse(BaseModel):
    """Metadata summary of a conversation session."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Session UUID")
    user_id: str = Field(..., description="Owner user ID")
    title: str = Field(..., description="Session title or topic")
    status: str = Field(..., description="Session status (active, archived, closed)")
    bridge_summary: str | None = Field(default=None, description="Bridge summary if branched")
    parent_session_id: str | None = Field(default=None, description="Parent session ID if branched")
    last_active_at: str = Field(..., description="ISO8601 timestamp of last activity")
    created_at: str = Field(..., description="ISO8601 timestamp of session creation")


class ChatSessionItem(BaseModel):
    """Single session item for sidebar history."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Session UUID")
    user_id: str = Field(..., description="Owner user ID")
    title: str = Field(..., description="Session title or topic")
    status: str = Field(..., description="Session status")
    bridge_summary: str | None = Field(default=None)
    parent_session_id: str | None = Field(default=None)
    last_active_at: datetime = Field(...)
    created_at: datetime = Field(...)
    updated_at: datetime = Field(...)
    date_group: str = Field(default="Today")
    message_count: int = Field(default=0)


class ChatSessionListResponse(BaseModel):
    """Paginated session list with date grouping metadata."""

    model_config = ConfigDict(extra="ignore")

    sessions: list[ChatSessionItem] = Field(default_factory=list)
    total: int = Field(...)
    limit: int = Field(...)
    offset: int = Field(...)
    has_more: bool = Field(...)
    groups: dict[str, list[ChatSessionItem]] = Field(default_factory=dict)


class ChatMessageResponse(BaseModel):
    """Chronological dialogue turn message item."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(...)
    session_id: str = Field(...)
    user_id: str = Field(...)
    role: str = Field(...)
    content: str = Field(...)
    tokens: int = Field(default=0)
    created_at: datetime = Field(...)


class ChatSessionDeleteResponse(BaseModel):
    """Confirmation payload for session deletion."""

    model_config = ConfigDict(extra="ignore")

    success: bool = True
    session_id: str
    message: str = "Session deleted successfully"


__all__ = [
    "ChatMessageResponse",
    "ChatSessionDeleteResponse",
    "ChatSessionItem",
    "ChatSessionListResponse",
    "ChatStreamRequest",
    "GreetingResponse",
    "SessionInfoResponse",
    "WSMessageIn",
    "WSMessageOut",
    "compute_date_group",
]
