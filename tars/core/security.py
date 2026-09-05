"""Security, Password Hashing, and JWT Token Management for TARS."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from tars.config import get_settings

logger = logging.getLogger("tars.core.security")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        return bool(bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8")))
    except Exception as e:
        logger.warning("Password verification failed: %s", e)
        return False


def get_password_hash(password: str) -> str:
    """Generate bcrypt hash for plain text password."""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def hash_password(password: str) -> str:
    """Alias for get_password_hash."""
    return get_password_hash(password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """Asynchronously verify password without blocking the event loop."""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


async def get_password_hash_async(password: str) -> str:
    """Asynchronously generate bcrypt hash without blocking the event loop."""
    return await asyncio.to_thread(get_password_hash, password)


async def hash_password_async(password: str) -> str:
    """Alias for get_password_hash_async."""
    return await get_password_hash_async(password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Generate signed JWT access token."""
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({"exp": expire, "iat": datetime.now(UTC)})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return str(encoded_jwt)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.PyJWTError as e:
        logger.debug("JWT decode error: %s", e)
        return None


__all__ = [
    "create_access_token",
    "decode_access_token",
    "get_password_hash",
    "get_password_hash_async",
    "hash_password",
    "hash_password_async",
    "verify_password",
    "verify_password_async",
]
