"""Chat and Streaming Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChatStreamRequest(BaseModel):
    """Payload for initiating a real-time SSE token stream."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default="default_session", description="Conversation session ID")
    message: str = Field(..., min_length=1, description="Non-empty user query")


class WSMessageIn(BaseModel):
    """Incoming WebSocket frame from client."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(default="chat_message", description="Message frame type")
    session_id: str = Field(default="ws_session", description="Dialogue session ID")
    content: str = Field(default="", description="User message content")


class WSMessageOut(BaseModel):
    """Outgoing WebSocket event frame to client."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(..., description="Event type: stream_start | token | stream_end | error")
    session_id: str | None = None
    content: str | None = None
    delta: str | None = None
    error: str | None = None


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


__all__ = [
    "ChatStreamRequest",
    "GreetingResponse",
    "SessionInfoResponse",
    "WSMessageIn",
    "WSMessageOut",
]
