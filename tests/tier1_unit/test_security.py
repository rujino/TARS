"""Tier 1 Unit Tests: Async Authentication Hygiene & Password Security (ASY-02).

Verifies:
1. Synchronous password hashing and verification backward compatibility.
2. Asynchronous password hashing and verification non-blocking behavior.
3. Event loop non-blocking property: concurrent heartbeat tasks continue ticking during bcrypt hashing.
4. JWT token issuance, claims validation, expiration, and tampering rejection.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from tars.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    get_password_hash_async,
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)


def test_sync_password_hashing_and_verification() -> None:
    """Verify synchronous bcrypt hashing and verification functions work correctly."""
    plain = "TarsTactical2026!#"
    hashed = get_password_hash(plain)

    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("WrongPassword123", hashed) is False
    assert hash_password(plain) != plain


@pytest.mark.asyncio
async def test_async_password_hashing_and_verification() -> None:
    """Verify non-blocking async bcrypt functions work correctly."""
    plain = "EnduranceMissionKey99"
    hashed = await get_password_hash_async(plain)

    assert hashed != plain
    assert await verify_password_async(plain, hashed) is True
    assert await verify_password_async("InvalidAttempt", hashed) is False

    # Test alias
    hashed2 = await hash_password_async(plain)
    assert await verify_password_async(plain, hashed2) is True


def test_password_truncation_symmetric_over_72_bytes() -> None:
    """Verify passwords exceeding 72 bytes (ASCII and multi-byte UTF-8) are verified symmetrically."""
    # 80-character ASCII password (80 bytes)
    ascii_80 = "A" * 80
    hashed_ascii = get_password_hash(ascii_80)
    assert verify_password(ascii_80, hashed_ascii) is True
    assert verify_password(ascii_80[:71] + "B", hashed_ascii) is False

    # Multi-byte Korean passphrase (> 72 bytes: 29 chars * 3 bytes per Hangul + punctuation ~ 75+ bytes)
    korean_passphrase = "인터스텔라_우주선_엔듀어런스호_타스_쿠퍼_머프_블랜드"
    assert len(korean_passphrase.encode("utf-8")) > 72
    hashed_korean = get_password_hash(korean_passphrase)
    assert verify_password(korean_passphrase, hashed_korean) is True
    assert verify_password("틀린비밀번호", hashed_korean) is False


@pytest.mark.asyncio
async def test_async_password_truncation_symmetric_over_72_bytes() -> None:
    """Verify async password verification for strings exceeding 72 bytes."""
    long_ascii = "Z" * 100
    hashed = await get_password_hash_async(long_ascii)
    assert await verify_password_async(long_ascii, hashed) is True
    assert await verify_password_async("WrongPassword", hashed) is False

    korean_long = "블랙홀_가르간튀아_사건의지평선_중력방정식_양자데이터_수집완료"
    assert len(korean_long.encode("utf-8")) > 72
    k_hashed = await get_password_hash_async(korean_long)
    assert await verify_password_async(korean_long, k_hashed) is True



@pytest.mark.asyncio
async def test_async_password_hashing_concurrency_nonblocking() -> None:
    """Verify running multiple password hash operations concurrently does not starve the event loop.

    A background heartbeat task ticks every 10ms.
    If bcrypt was blocking the event loop, the heartbeat would starve (< 5 ticks).
    With asyncio.to_thread, the event loop remains responsive and accumulates many ticks.
    """
    heartbeat_ticks = 0
    running = True

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while running:
            await asyncio.sleep(0.01)  # 10ms
            heartbeat_ticks += 1

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        # Run 4 bcrypt hash operations concurrently via thread pool
        passwords = [f"PasswordNum_{i}_Secure" for i in range(4)]
        hashes = await asyncio.gather(*[get_password_hash_async(p) for p in passwords])

        assert len(hashes) == 4
        for p, h in zip(passwords, hashes):
            assert await verify_password_async(p, h) is True

        # Heartbeat must have ticked significantly during the ~800ms of CPU hashing
        assert heartbeat_ticks >= 15, (
            f"Event loop was starved! Heartbeat ticks recorded: {heartbeat_ticks} (expected >= 15)"
        )
    finally:
        running = False
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


def test_jwt_access_token_creation_and_decoding() -> None:
    """Verify JWT token encoding and decoding round-trip."""
    user_id = "user_uuid_12345"
    token = create_access_token(data={"sub": user_id}, expires_delta=timedelta(minutes=15))

    assert isinstance(token, str)
    payload = decode_access_token(token)

    assert payload is not None
    assert payload.get("sub") == user_id
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_token_expiration_and_tampering() -> None:
    """Verify expired or tampered tokens return None."""
    user_id = "user_uuid_expired"
    # Create token that expired 10 minutes ago
    expired_token = create_access_token(data={"sub": user_id}, expires_delta=timedelta(minutes=-10))
    assert decode_access_token(expired_token) is None

    # Tampered token
    tampered = expired_token[:-4] + "abcd"
    assert decode_access_token(tampered) is None

    # Garbage token
    assert decode_access_token("completely.invalid.token") is None
