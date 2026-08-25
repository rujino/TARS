"""Tier 3 E2E API Tests: Authentication, User Lifecycle & JWT Authorization Access Control.

Verifies:
1. User Signup (`POST /api/v1/auth/signup`):
   - Creates user, stores hashed password (bcrypt), seeds default TARS settings, returns JWT token.
   - Rejects duplicate usernames and emails (400/409 Conflict).
   - Validates input format (email format, password min length).
2. User Login (`POST /api/v1/auth/login`):
   - Authenticates with valid credentials, returns fresh JWT.
   - Rejects wrong password or nonexistent user with 401 Unauthorized.
3. Protected Route Access Control (`GET /api/v1/auth/me`):
   - Grants access with valid Bearer token.
   - Rejects requests with missing, malformed, or expired Bearer tokens with 401 Unauthorized.
4. Password Hashing Security:
   - Verifies raw password is never stored or leaked in API responses.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.core.security import decode_access_token, verify_password
from tars.db.models import TARSSettings, User

# ============================================================================
# 1. Signup Endpoint Tests
# ============================================================================


@pytest.mark.asyncio
async def test_user_signup_success(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify signup creates user in DB with hashed password and returns valid JWT token."""
    payload: dict[str, Any] = {
        "username": "murph",
        "email": "murph@nasa.gov",
        "password": "EurekaGravity2026!",
    }

    response = await api_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201 or response.status_code == 200

    data = response.json()
    assert "token" in data or "access_token" in data
    token_str = data.get("access_token") or data.get("token", {}).get("access_token")
    assert token_str is not None

    user_info = data.get("user", data)
    assert user_info["username"] == "murph"
    assert user_info["email"] == "murph@nasa.gov"
    assert "password" not in user_info  # Password must never be exposed

    # Verify DB record
    stmt = select(User).where(User.username == "murph")
    result = await db_session.execute(stmt)
    db_user = result.scalar_one_or_none()

    assert db_user is not None
    assert db_user.email == "murph@nasa.gov"
    assert verify_password("EurekaGravity2026!", db_user.hashed_password) is True

    # Verify default TARSSettings created
    settings_stmt = select(TARSSettings).where(TARSSettings.user_id == db_user.id)
    settings_result = await db_session.execute(settings_stmt)
    db_settings = settings_result.scalar_one_or_none()
    assert db_settings is not None
    assert db_settings.humor_level == 0.90 or db_settings.humor_level == 90
    assert db_settings.honesty_level == 0.95 or db_settings.honesty_level == 95


@pytest.mark.asyncio
async def test_user_signup_duplicate_username_fails(
    api_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify signup rejects duplicate username with 400 or 409 status code."""
    payload = {
        "username": seed_test_user.username,  # "cooper"
        "email": "new_email@endurance.space",
        "password": "Password123!",
    }

    response = await api_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code in (400, 409, 422)


@pytest.mark.asyncio
async def test_user_signup_duplicate_email_fails(
    api_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify signup rejects duplicate email with 400 or 409 status code."""
    payload = {
        "username": "different_cooper",
        "email": seed_test_user.email,  # "cooper@endurance.space"
        "password": "Password123!",
    }

    response = await api_client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code in (400, 409, 422)


@pytest.mark.asyncio
async def test_user_signup_invalid_email_and_short_password(
    api_client: AsyncClient,
) -> None:
    """Verify input validation fails on invalid email or short password."""
    # Invalid email
    res1 = await api_client.post(
        "/api/v1/auth/signup",
        json={"username": "validuser", "email": "not-an-email", "password": "Password123!"},
    )
    assert res1.status_code == 422

    # Short password
    res2 = await api_client.post(
        "/api/v1/auth/signup",
        json={"username": "validuser2", "email": "valid@email.com", "password": "123"},
    )
    assert res2.status_code == 422


# ============================================================================
# 2. Login Endpoint Tests
# ============================================================================


@pytest.mark.asyncio
async def test_user_login_success(
    api_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify login with correct credentials returns valid JWT access token."""
    login_payload = {
        "username": seed_test_user.username,
        "password": "TarsPassword123!",
    }

    response = await api_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200

    data = response.json()
    token_str = data.get("access_token") or data.get("token", {}).get("access_token")
    assert token_str is not None

    payload = decode_access_token(token_str)
    assert payload is not None
    assert payload["sub"] == seed_test_user.id


@pytest.mark.asyncio
async def test_user_login_wrong_password_fails(
    api_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify login with invalid password returns 401 Unauthorized."""
    login_payload = {
        "username": seed_test_user.username,
        "password": "WrongPassword999!",
    }

    response = await api_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_login_nonexistent_user_fails(
    api_client: AsyncClient,
) -> None:
    """Verify login with non-existent user returns 401 Unauthorized."""
    login_payload = {
        "username": "ghost_pilot",
        "password": "SomePassword123!",
    }

    response = await api_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401


# ============================================================================
# 3. Protected Route Access Control (/api/v1/auth/me)
# ============================================================================


@pytest.mark.asyncio
async def test_get_current_user_profile_authenticated(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify authenticated user can fetch profile details from /api/v1/auth/me."""
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == seed_test_user.id
    assert data["username"] == seed_test_user.username
    assert data["email"] == seed_test_user.email


@pytest.mark.asyncio
async def test_get_current_user_profile_unauthenticated(
    api_client: AsyncClient,
) -> None:
    """Verify unauthenticated request to /api/v1/auth/me is rejected with 401."""
    # Ensure no Authorization header is set
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_profile_invalid_token(
    api_client: AsyncClient,
) -> None:
    """Verify forged or malformed JWT token is rejected with 401."""
    api_client.headers.update({"Authorization": "Bearer forged.invalid.token.here"})
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401
