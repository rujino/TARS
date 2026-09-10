"""TARS Persona Configuration REST router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from tars.api.dependencies import get_current_user, get_user_settings_service
from tars.domains.auth.models import User
from tars.domains.persona.schemas import (
    TARSConfigResponse,
    TARSConfigUpdateRequest,
)
from tars.domains.persona.service import UserSettingsService

logger = logging.getLogger("tars.domains.persona.router")
router = APIRouter(prefix="/tars/config", tags=["TARS Persona Configuration"])


@router.get(
    "",
    response_model=TARSConfigResponse,
    summary="Get current user's TARS persona settings",
)
async def get_config(
    current_user: User = Depends(get_current_user),
    settings_service: UserSettingsService = Depends(get_user_settings_service),
) -> TARSConfigResponse:
    """Return the active humor, honesty, and operational mode configuration."""
    settings = await settings_service.get_or_create_settings(current_user.id)
    return TARSConfigResponse.model_validate(settings)


@router.patch(
    "",
    response_model=TARSConfigResponse,
    summary="Partially update TARS persona parameters",
)
async def patch_config(
    payload: TARSConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    settings_service: UserSettingsService = Depends(get_user_settings_service),
) -> TARSConfigResponse:
    """Update persona parameters such as humor_level, honesty_level, and mode."""
    settings = await settings_service.update_settings(current_user.id, payload)
    return TARSConfigResponse.model_validate(settings)


@router.post(
    "/reset",
    response_model=TARSConfigResponse,
    summary="Reset TARS persona parameters to Interstellar defaults",
)
async def reset_config(
    current_user: User = Depends(get_current_user),
    settings_service: UserSettingsService = Depends(get_user_settings_service),
) -> TARSConfigResponse:
    """Reset configuration back to Humor: 90%, Honesty: 95%, Mode: companion."""
    settings = await settings_service.reset_settings(current_user.id)
    return TARSConfigResponse.model_validate(settings)


__all__ = ["router"]
