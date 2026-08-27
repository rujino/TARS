"""Authentication and user management REST router."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.dependencies import get_current_user, get_db_session
from tars.api.schemas import (
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)
from tars.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from tars.db.models import TARSSettings, User

logger = logging.getLogger("tars.api.routers.auth")
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user account",
)
async def signup(
    payload: UserSignupRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Register a new user, create default TARS settings, and return access token."""
    # Check for existing user with same username or email
    stmt = select(User).where(or_(User.username == payload.username, User.email == payload.email))
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing is not None:
        if existing.username == payload.username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email address already registered",
        )

    # Create User and default TARSSettings
    now = datetime.now(UTC)
    hashed_pwd = get_password_hash(payload.password)

    new_user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hashed_pwd,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(new_user)
    await db.flush()  # populate new_user.id

    default_settings = TARSSettings(
        user_id=new_user.id,
        humor_level=0.90,
        honesty_level=0.95,
        mode="companion",
        created_at=now,
        updated_at=now,
    )
    db.add(default_settings)
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token(data={"sub": new_user.id})

    user_resp = UserResponse.model_validate(new_user).model_dump()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_resp,
    }


@router.post(
    "/login",
    response_model=dict[str, Any],
    summary="Authenticate and receive access token",
)
async def login(
    payload: UserLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Verify username and password and generate fresh JWT token."""
    stmt = select(User).where(User.username == payload.username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive",
        )

    token = create_access_token(data={"sub": user.id})
    user_resp = UserResponse.model_validate(user).model_dump()
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_resp,
    }


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return profile details for active bearer token."""
    return UserResponse.model_validate(current_user)


__all__ = ["router"]
