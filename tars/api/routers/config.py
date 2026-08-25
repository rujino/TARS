"""TARS Persona Configuration REST router."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.dependencies import get_current_user, get_db_session
from tars.api.schemas import (
    TARSConfigResponse,
    TARSConfigUpdateRequest,
)
from tars.db.models import TARSSettings, User

logger = logging.getLogger("tars.api.routers.config")
router = APIRouter(prefix="/tars/config", tags=["TARS Persona Configuration"])


async def _get_or_create_settings(db: AsyncSession, user_id: str) -> TARSSettings:
    """Helper to fetch active settings or seed defaults."""
    stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
    res = await db.execute(stmt)
    settings = res.scalar_one_or_none()

    if settings is None:
        now = datetime.now(UTC)
        settings = TARSSettings(
            user_id=user_id,
            humor_level=0.90,
            honesty_level=0.95,
            mode="companion",
            created_at=now,
            updated_at=now,
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


@router.get(
    "",
    response_model=TARSConfigResponse,
    summary="Get current user's TARS persona settings",
)
async def get_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TARSConfigResponse:
    """Return the active humor, honesty, and operational mode configuration."""
    settings = await _get_or_create_settings(db, current_user.id)
    return TARSConfigResponse.model_validate(settings)


@router.patch(
    "",
    response_model=TARSConfigResponse,
    summary="Partially update TARS persona parameters",
)
async def patch_config(
    payload: TARSConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TARSConfigResponse:
    """Update persona parameters such as humor_level, honesty_level, and mode."""
    settings = await _get_or_create_settings(db, current_user.id)

    if payload.humor_level is not None:
        settings.humor_level = payload.humor_level
    if payload.honesty_level is not None:
        settings.honesty_level = payload.honesty_level
    if payload.mode is not None:
        settings.mode = payload.mode

    settings.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(settings)

    return TARSConfigResponse.model_validate(settings)


@router.post(
    "/reset",
    response_model=TARSConfigResponse,
    summary="Reset TARS persona parameters to Interstellar defaults",
)
async def reset_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TARSConfigResponse:
    """Reset configuration back to Humor: 90%, Honesty: 95%, Mode: companion."""
    settings = await _get_or_create_settings(db, current_user.id)

    settings.humor_level = 0.90
    settings.honesty_level = 0.95
    settings.mode = "companion"
    settings.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(settings)

    return TARSConfigResponse.model_validate(settings)


__all__ = ["router"]
