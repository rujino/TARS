"""TARS Tier 1 Micro Fact Storage Manager.

Handles reading, updating, and saving user personal context facts and profile slots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from tars.config import get_settings
from tars.domains.knowledge.micro.schemas import MicroFact, UserMicroFactProfile
from tars.domains.knowledge.storage.manager import (
    FileStorageManager,
    StorageIOError,
    StorageSecurityError,
)

logger = logging.getLogger("tars.domains.knowledge.micro.manager")


class MicroFactManager:
    """Manages persistence and retrieval of Tier 1 User Micro Facts."""

    def __init__(self, storage_manager: FileStorageManager | None = None) -> None:
        self.storage_manager = storage_manager or FileStorageManager()

    def _get_profile_path(self, user_id: str) -> Path:
        """Get the isolated JSON file path for a user's micro facts profile."""
        clean_user_id = self.storage_manager._validate_id(user_id, "user_id")
        user_dir = (self.storage_manager.base_dir / "users" / clean_user_id).resolve()
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "_micro_facts.json"

    async def get_profile(self, user_id: str) -> UserMicroFactProfile:
        """Load user micro fact profile from disk, or return empty profile if not found."""
        path = self._get_profile_path(user_id)
        if not path.exists():
            return UserMicroFactProfile(user_id=user_id)

        try:
            content = await asyncio.to_thread(path.read_text, encoding="utf-8")
            data = json.loads(content)
            return UserMicroFactProfile.model_validate(data)
        except Exception as exc:
            logger.warning(
                "Failed to read micro facts for user '%s', falling back to empty profile: %s",
                user_id,
                exc,
            )
            return UserMicroFactProfile(user_id=user_id)

    async def save_profile(self, profile: UserMicroFactProfile) -> None:
        """Atomically persist user micro fact profile to disk."""
        path = self._get_profile_path(profile.user_id)
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")

        try:
            data = profile.model_dump(mode="json")
            serialized = json.dumps(data, indent=2, ensure_ascii=False)
            await asyncio.to_thread(tmp_path.write_text, serialized, encoding="utf-8")
            await asyncio.to_thread(tmp_path.replace, path)
        except Exception as exc:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise StorageIOError(f"Failed to persist micro facts for user '{profile.user_id}': {exc}") from exc

    async def set_fact(
        self,
        user_id: str,
        key: str,
        value: str,
        category: str = "preference",
        confidence: float = 1.0,
    ) -> MicroFact:
        """Record or update a single micro fact slot."""
        profile = await self.get_profile(user_id)
        fact = profile.set_fact(key=key, value=value, category=category, confidence=confidence)
        await self.save_profile(profile)
        return fact

    async def remove_fact(self, user_id: str, key: str) -> bool:
        """Delete a micro fact slot."""
        profile = await self.get_profile(user_id)
        deleted = profile.remove_fact(key=key)
        if deleted:
            await self.save_profile(profile)
        return deleted


__all__ = ["MicroFactManager"]
