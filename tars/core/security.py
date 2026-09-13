"""Security, Password Hashing, and JWT Token Management for TARS."""

from __future__ import annotations

import asyncio
import logging
import uuid
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


_consumed_ws_tickets: dict[str, float] = {}


def create_ws_ticket(
    user_id: str,
    expires_in_seconds: int = 30,
) -> str:
    """Generate a short-lived single-use ticket for WebSocket authentication."""
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(seconds=expires_in_seconds)
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "ws_ticket",
        "jti": str(uuid.uuid4()),
        "exp": expire,
        "iat": now,
    }
    encoded = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return str(encoded)


def validate_and_consume_ws_ticket(ticket: str) -> str | None:
    """Validate a single-use WebSocket ticket and immediately consume it to prevent replay."""
    payload = decode_access_token(ticket)
    if payload is None or payload.get("type") != "ws_ticket":
        return None

    jti = payload.get("jti")
    sub = payload.get("sub")
    if not jti or not sub:
        return None

    now_ts = datetime.now(UTC).timestamp()
    exp_ts = float(payload.get("exp", 0))
    if now_ts > exp_ts:
        return None

    global _consumed_ws_tickets
    if jti in _consumed_ws_tickets:
        logger.warning("WebSocket ticket reuse attempt blocked (jti=%s, user=%s)", jti, sub)
        return None

    _consumed_ws_tickets[jti] = exp_ts

    # Prune expired tickets if cache grows
    if len(_consumed_ws_tickets) > 200:
        expired_jtis = [k for k, v in _consumed_ws_tickets.items() if now_ts > v]
        for k in expired_jtis:
            _consumed_ws_tickets.pop(k, None)

    return str(sub)


def _get_fernet() -> Any:
    """Derive deterministic Fernet cipher instance from jwt_secret_key."""
    import base64
    import hashlib

    from cryptography.fernet import Fernet

    settings = get_settings()
    digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a sensitive plaintext secret string with AES-128-CBC (Fernet)."""
    if not plaintext:
        return plaintext
    if plaintext.startswith("enc:"):
        return plaintext
    try:
        f = _get_fernet()
        ciphertext = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return f"enc:{ciphertext}"
    except Exception as exc:
        logger.error("Failed to encrypt secret: %s", exc)
        return plaintext


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Decrypt a sensitive secret, transparently handling legacy plaintext tokens."""
    if not ciphertext:
        return ciphertext
    if not ciphertext.startswith("enc:"):
        return ciphertext
    try:
        from cryptography.fernet import InvalidToken

        f = _get_fernet()
        raw_b64 = ciphertext[4:]
        decrypted = f.decrypt(raw_b64.encode("utf-8"))
        return str(decrypted.decode("utf-8"))
    except InvalidToken:
        logger.warning("Invalid token during secret decryption, returning raw value")
        return ciphertext
    except Exception as exc:
        logger.error("Secret decryption error: %s", exc)
        return ciphertext


__all__ = [
    "create_access_token",
    "create_ws_ticket",
    "decode_access_token",
    "decrypt_secret",
    "encrypt_secret",
    "get_password_hash",
    "get_password_hash_async",
    "hash_password",
    "hash_password_async",
    "validate_and_consume_ws_ticket",
    "verify_password",
    "verify_password_async",
]
