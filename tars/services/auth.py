"""Authentication and user management business service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.schemas.auth import (
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)
from tars.core.security import (
    create_access_token,
    get_password_hash_async,
    verify_password_async,
)
from tars.db.models import TARSSettings, User

# ============================================================================
# Domain Exceptions (Decoupled from HTTP / Web Framework)
# ============================================================================


class AuthError(Exception):
    """Base exception for authentication service errors."""


class UsernameAlreadyTakenError(AuthError):
    """Raised when signup username is already registered."""


class EmailAlreadyRegisteredError(AuthError):
    """Raised when signup email is already registered."""


class InvalidCredentialsError(AuthError):
    """Raised when username or password does not match."""


class InactiveUserError(AuthError):
    """Raised when an authenticated user account is disabled."""


# ============================================================================
# Service
# ============================================================================


class AuthService:
    """Encapsulates user account creation, verification, and JWT issuance."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def signup(self, payload: UserSignupRequest) -> dict[str, Any]:
        """Register a new user, create default TARS settings, and return access token."""
        stmt = select(User).where(or_(User.username == payload.username, User.email == payload.email))
        res = await self.db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing is not None:
            if existing.username == payload.username:
                raise UsernameAlreadyTakenError("Username already taken")
            raise EmailAlreadyRegisteredError("Email address already registered")

        now = datetime.now(UTC)
        hashed_pwd = await get_password_hash_async(payload.password)

        new_user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=hashed_pwd,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.db.add(new_user)
        await self.db.flush()  # populate new_user.id

        default_settings = TARSSettings(
            user_id=new_user.id,
            humor_level=0.90,
            honesty_level=0.95,
            mode="companion",
            created_at=now,
            updated_at=now,
        )
        self.db.add(default_settings)
        await self.db.commit()
        await self.db.refresh(new_user)

        token = create_access_token(data={"sub": new_user.id})
        user_resp = UserResponse.model_validate(new_user).model_dump()
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_resp,
        }

    async def login(self, payload: UserLoginRequest) -> dict[str, Any]:
        """Verify username and password and generate fresh JWT token."""
        stmt = select(User).where(User.username == payload.username)
        res = await self.db.execute(stmt)
        user = res.scalar_one_or_none()

        if user is None or not await verify_password_async(payload.password, user.hashed_password):
            raise InvalidCredentialsError("Invalid username or password")

        if not user.is_active:
            raise InactiveUserError("User account is inactive")

        token = create_access_token(data={"sub": user.id})
        user_resp = UserResponse.model_validate(user).model_dump()
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user_resp,
        }


__all__ = [
    "AuthError",
    "AuthService",
    "EmailAlreadyRegisteredError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "UsernameAlreadyTakenError",
]
