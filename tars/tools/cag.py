"""Static Context-Augmented Generation (Tool CAG) Manager for TARS.

Provides:
- Static System Prompt + Tool Schema Bundling
- In-Memory Hash Caching for low-latency retrieval
- Gemini Context Caching API integration with automatic in-memory fallback
- Cache Invalidation & Synchronization
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from tars.config import get_settings
from tars.persona.prompts import TARSPersonaManager
from tars.tools.registry import ToolRegistry

logger = logging.getLogger("tars.tools.cag")


class ToolCAGManager:
    """Manages Static Context-Augmented Generation (CAG) for System Instructions and Tool Schemas."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        persona_manager: TARSPersonaManager | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.persona_manager = persona_manager or TARSPersonaManager()
        settings = get_settings()
        self.ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.cag_cache_ttl_seconds
        )
        self._cached_content_id: str | None = None
        self._cache_hash: str = ""
        self._cached_bundle: dict[str, Any] | None = None
        self._cached_at: datetime | None = None

    def get_static_instructions(self) -> str:
        """Compose static base system instructions without dynamic XML OKF slices."""
        return self.persona_manager.build_system_prompt(
            humor_level=0.90,
            honesty_level=0.95,
            mode="companion",
            context_docs=None,
        )

    def compute_cache_hash(self) -> str:
        """Compute deterministic SHA256 hash of static prompt instructions and tool declarations."""
        instructions = self.get_static_instructions()
        tools = self.tool_registry.export_gemini_declarations()
        payload = json.dumps(
            {"instructions": instructions, "tools": tools},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_static_cag_bundle(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return the bundled static CAG payload with in-memory caching.

        Args:
            force_refresh: Whether to ignore cached bundle and recompute.

        Returns:
            Dictionary containing system_prompt, tools, cache_hash, cached_content_id, and ttl.
        """
        now = datetime.now(timezone.utc)
        current_hash = self.compute_cache_hash()

        if (
            not force_refresh
            and self._cached_bundle is not None
            and self._cached_at is not None
            and (now - self._cached_at).total_seconds() < self.ttl_seconds
            and self._cache_hash == current_hash
        ):
            return self._cached_bundle

        instructions = self.get_static_instructions()
        tools = self.tool_registry.export_gemini_declarations()
        self._cache_hash = current_hash
        self._cached_at = now
        self._cached_bundle = {
            "system_prompt": instructions,
            "tools": tools,
            "cache_hash": self._cache_hash,
            "cached_content_id": self._cached_content_id,
            "ttl_seconds": self.ttl_seconds,
        }
        logger.debug(
            "Recomputed static CAG bundle (hash=%s, tools_count=%d, ttl=%ds)",
            self._cache_hash[:8],
            len(tools),
            self.ttl_seconds,
        )
        return self._cached_bundle

    # Alias for contract compatibility
    get_cag_bundle = get_static_cag_bundle

    async def sync_gemini_context_cache(
        self,
        client: Any,
        model_name: str | None = None,
    ) -> str | None:
        """Attempt to create or update Google GenAI Context Cache on server.

        If client is None or API fails (e.g. min tokens not reached, offline test),
        gracefully falls back to local in-memory CAG without raising errors.

        Args:
            client: Google GenAI client instance.
            model_name: Target Gemini model identifier.

        Returns:
            Cache resource name/id if created, None if skipped or fallen back.
        """
        if client is None:
            logger.debug("No GenAI client provided; using in-memory CAG cache.")
            return None

        bundle = self.get_static_cag_bundle()
        target_model = model_name or get_settings().gemini_model_name

        try:
            # Async GenAI SDK cache creation
            if hasattr(client, "aio") and hasattr(client.aio, "caches"):
                cache = await client.aio.caches.create(
                    model=target_model,
                    config={
                        "system_instruction": bundle["system_prompt"],
                        "ttl": f"{self.ttl_seconds}s",
                    },
                )
                self._cached_content_id = getattr(cache, "name", str(cache))
                logger.info("Created Gemini server context cache: %s", self._cached_content_id)
                self._cached_bundle = None  # refresh bundle with new cached_content_id
                self._cached_at = None
                return self._cached_content_id

            # Sync GenAI SDK cache creation
            if hasattr(client, "caches"):
                cache = client.caches.create(
                    model=target_model,
                    config={
                        "system_instruction": bundle["system_prompt"],
                        "ttl": f"{self.ttl_seconds}s",
                    },
                )
                self._cached_content_id = getattr(cache, "name", str(cache))
                logger.info(
                    "Created Gemini server context cache (sync): %s", self._cached_content_id
                )
                self._cached_bundle = None
                self._cached_at = None
                return self._cached_content_id

        except Exception as exc:
            logger.warning(
                "Gemini Context Caching API creation skipped or failed (%s: %s). Falling back to in-memory CAG.",
                type(exc).__name__,
                exc,
            )

        return None

    def invalidate_cache(self) -> None:
        """Invalidate all local and remote cache records."""
        self._cached_content_id = None
        self._cached_bundle = None
        self._cache_hash = ""
        self._cached_at = None
        logger.debug("ToolCAGManager cache invalidated.")


__all__ = [
    "ToolCAGManager",
]
