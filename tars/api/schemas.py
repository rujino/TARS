"""Pydantic request and response schemas for TARS FastAPI endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# ============================================================================
# Auth Schemas
# ============================================================================


class UserSignupRequest(BaseModel):
    """Payload for creating a new user account."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: EmailStr = Field(..., description="Valid user email address")
    password: str = Field(..., min_length=8, max_length=128, description="Strong account password")


class UserLoginRequest(BaseModel):
    """Payload for authenticating an existing user."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., description="User login identifier")
    password: str = Field(..., description="Account password")


class UserResponse(BaseModel):
    """Public user profile model (never returns hashed password)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TokenResponse(BaseModel):
    """JWT authorization token payload."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse | None = None


# ============================================================================
# TARS Configuration Schemas
# ============================================================================


class TARSConfigResponse(BaseModel):
    """Current TARS persona settings model."""

    model_config = ConfigDict(from_attributes=True)

    humor_level: float
    honesty_level: float
    mode: str


class TARSConfigUpdateRequest(BaseModel):
    """Partial update payload for TARS persona configuration."""

    model_config = ConfigDict(extra="forbid")

    humor_level: float | None = Field(
        default=None,
        description="Humor index in range 0.0 to 1.0 or 0 to 100",
    )
    honesty_level: float | None = Field(
        default=None,
        description="Honesty index in range 0.0 to 1.0 or 0 to 100",
    )
    mode: Literal["companion", "work"] | None = Field(
        default=None,
        description="Operational mode ('companion' or 'work')",
    )

    @field_validator("humor_level", "honesty_level")
    @classmethod
    def validate_levels(cls, v: float | None) -> float | None:
        if v is None:
            return None
        # Normalize 0-100 percentage to 0.0-1.0 if needed
        if 1.0 < v <= 100.0:
            v = v / 100.0
        if v < 0.0 or v > 1.0:
            raise ValueError("Level parameters must be between 0.0 and 1.0 (or 0 and 100)")
        return round(float(v), 4)


# ============================================================================
# Chat & Streaming Schemas
# ============================================================================


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
    "TARSConfigResponse",
    "TARSConfigUpdateRequest",
    "TokenResponse",
    "UserLoginRequest",
    "UserResponse",
    "UserSignupRequest",
    "WSMessageIn",
    "WSMessageOut",
]
