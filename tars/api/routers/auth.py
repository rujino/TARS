"""Authentication and user management REST router.

Thin Controller pattern: Delegates registration, verification, and token issuance to AuthService.
Maps domain-level exceptions to HTTP status codes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from tars.api.dependencies import get_auth_service, get_current_user
from tars.api.schemas import (
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)
from tars.db.models import User
from tars.services.auth import (
    AuthService,
    EmailAlreadyRegisteredError,
    InactiveUserError,
    InvalidCredentialsError,
    UsernameAlreadyTakenError,
)

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
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Register a new user, create default TARS settings, and return access token."""
    try:
        return await auth_service.signup(payload)
    except UsernameAlreadyTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email address already registered",
        )


@router.post(
    "/login",
    response_model=dict[str, Any],
    summary="Authenticate and receive access token",
)
async def login(
    payload: UserLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Verify username and password and generate fresh JWT token."""
    try:
        return await auth_service.login(payload)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InactiveUserError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive",
        )


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
