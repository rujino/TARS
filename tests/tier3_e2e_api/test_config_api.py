"""Tier 3 E2E API Tests: TARS Persona Settings & Configuration REST Endpoints.

Verifies:
1. `GET /api/v1/tars/config`:
   - Returns current user's TARS persona parameters (humor_level, honesty_level, mode, TTS params).
2. `PATCH /api/v1/tars/config`:
   - Partially updates persona parameters (e.g., dial down humor, switch to work mode).
   - Validates range boundaries (humor 0.0-1.0 or 0-100, valid modes).
3. `POST /api/v1/tars/config/reset`:
   - Resets persona back to Interstellar signature defaults (Humor: 90%, Honesty: 95%, Mode: companion).
4. Access Control:
   - Unauthenticated requests return 401 Unauthorized.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.db.models import TARSSettings, User

# ============================================================================
# 1. GET /api/v1/tars/config Tests
# ============================================================================


@pytest.mark.asyncio
async def test_get_tars_config_authenticated(
    auth_client: AsyncClient,
    seed_test_user: User,
) -> None:
    """Verify authenticated user receives current TARS configuration."""
    response = await auth_client.get("/api/v1/tars/config")
    assert response.status_code == 200

    data = response.json()
    assert "humor_level" in data
    assert "honesty_level" in data
    assert "mode" in data

    # Default values check
    assert data["humor_level"] in (0.90, 90)
    assert data["honesty_level"] in (0.95, 95)
    assert data["mode"] == "companion"


@pytest.mark.asyncio
async def test_get_tars_config_unauthenticated(
    api_client: AsyncClient,
) -> None:
    """Verify unauthenticated request is rejected with 401."""
    response = await api_client.get("/api/v1/tars/config")
    assert response.status_code == 401


# ============================================================================
# 2. PATCH /api/v1/tars/config Tests
# ============================================================================


@pytest.mark.asyncio
async def test_patch_tars_config_partial_update(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    seed_test_user: User,
) -> None:
    """Verify partial updates to humor_level and mode persist in DB and return updated state."""
    patch_payload: dict[str, Any] = {
        "humor_level": 0.50,
        "mode": "work",
    }

    response = await auth_client.patch("/api/v1/tars/config", json=patch_payload)
    assert response.status_code == 200

    data = response.json()
    assert data["humor_level"] in (0.50, 50)
    assert data["mode"] == "work"
    assert data["honesty_level"] in (0.95, 95)  # Untouched parameter preserved

    # Verify DB persistence
    user_id = seed_test_user.id
    db_session.expire_all()
    stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
    result = await db_session.execute(stmt)
    db_settings = result.scalar_one()

    assert db_settings.humor_level in (0.50, 50)
    assert db_settings.mode == "work"


@pytest.mark.asyncio
async def test_patch_tars_config_invalid_values_rejected(
    auth_client: AsyncClient,
) -> None:
    """Verify out-of-range humor values or unknown modes are rejected with 422 Unprocessable Entity."""
    # Negative humor
    res1 = await auth_client.patch("/api/v1/tars/config", json={"humor_level": -0.5})
    assert res1.status_code == 422

    # Excess humor
    res2 = await auth_client.patch("/api/v1/tars/config", json={"humor_level": 150})
    assert res2.status_code == 422

    # Invalid mode
    res3 = await auth_client.patch("/api/v1/tars/config", json={"mode": "berserk_mode"})
    assert res3.status_code == 422


# ============================================================================
# 3. POST /api/v1/tars/config/reset Tests
# ============================================================================


@pytest.mark.asyncio
async def test_reset_tars_config_to_defaults(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    seed_test_user: User,
) -> None:
    """Verify reset endpoint restores Interstellar signature configuration."""
    # 1. First alter the config
    await auth_client.patch(
        "/api/v1/tars/config",
        json={"humor_level": 0.10, "honesty_level": 0.50, "mode": "work"},
    )

    # 2. Call reset
    response = await auth_client.post("/api/v1/tars/config/reset")
    assert response.status_code == 200

    data = response.json()
    assert data["humor_level"] in (0.90, 90)
    assert data["honesty_level"] in (0.95, 95)
    assert data["mode"] == "companion"

    # 3. Verify in DB
    stmt = select(TARSSettings).where(TARSSettings.user_id == seed_test_user.id)
    result = await db_session.execute(stmt)
    db_settings = result.scalar_one()

    assert db_settings.humor_level in (0.90, 90)
    assert db_settings.honesty_level in (0.95, 95)
    assert db_settings.mode == "companion"


@pytest.mark.asyncio
async def test_reset_tars_config_unauthenticated(
    api_client: AsyncClient,
) -> None:
    """Verify reset endpoint requires authentication."""
    response = await api_client.post("/api/v1/tars/config/reset")
    assert response.status_code == 401
