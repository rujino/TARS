"""TARS User Settings and Persona Configuration Service."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tars.api.schemas.config import TARSConfigUpdateRequest
from tars.db.models import TARSSettings


class UserSettingsService:
    """Business service for retrieving and managing user persona and feature settings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create_settings(self, user_id: str) -> TARSSettings:
        """Fetch active user settings or seed default configuration."""
        stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
        res = await self.db.execute(stmt)
        settings = res.scalar_one_or_none()

        if settings is None:
            now = datetime.now(UTC)
            settings = TARSSettings(
                user_id=user_id,
                humor_level=0.90,
                honesty_level=0.95,
                mode="companion",
                disabled_tools=[],
                google_mock_linked=False,
                created_at=now,
                updated_at=now,
            )
            self.db.add(settings)
            await self.db.commit()
            await self.db.refresh(settings)

        return settings

    async def update_settings(
        self, user_id: str, payload: TARSConfigUpdateRequest
    ) -> TARSSettings:
        """Partially update persona configuration parameters."""
        settings = await self.get_or_create_settings(user_id)

        if payload.humor_level is not None:
            settings.humor_level = payload.humor_level
        if payload.honesty_level is not None:
            settings.honesty_level = payload.honesty_level
        if payload.mode is not None:
            settings.mode = payload.mode

        settings.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(settings)
        return settings

    async def reset_settings(self, user_id: str) -> TARSSettings:
        """Reset configuration back to Interstellar defaults."""
        settings = await self.get_or_create_settings(user_id)

        settings.humor_level = 0.90
        settings.honesty_level = 0.95
        settings.mode = "companion"
        settings.updated_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(settings)
        return settings


__all__ = ["UserSettingsService"]
