"""Auth request and response Pydantic schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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
    email: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TokenResponse(BaseModel):
    """JWT authorization token payload."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse | None = None


__all__ = [
    "TokenResponse",
    "UserLoginRequest",
    "UserResponse",
    "UserSignupRequest",
]
