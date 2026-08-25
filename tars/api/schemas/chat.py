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


__all__ = [
    "ChatStreamRequest",
    "WSMessageIn",
    "WSMessageOut",
]
