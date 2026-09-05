"""Tier 1 Unit Tests: ToolCAGManager Cache TTL Invalidation & Recalculation (RES-04)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tars.tools.base import BaseTool
from tars.tools.cag import ToolCAGManager
from tars.tools.registry import ToolRegistry


class SimpleEchoTool(BaseTool):
    """Simple test tool for ToolCAGManager tests."""

    def __init__(self) -> None:
        super().__init__(
            name="echo_tool",
            description="Echoes the provided message.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Text to echo"},
                },
                "required": ["message"],
            },
        )

    async def aexecute(self, **kwargs: Any) -> Any:
        return kwargs.get("message", "")


def test_cag_initial_state() -> None:
    """Verify initial ToolCAGManager cache state."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=60)

    assert cag._cached_at is None
    assert cag._cached_bundle is None
    assert cag._cache_hash == ""
    assert cag._cached_content_id is None
    assert cag.ttl_seconds == 60


def test_cag_bundle_caching_and_ttl_expiration() -> None:
    """Verify in-memory caching within TTL and automatic recomputation when TTL expires."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=10)

    # First fetch: computes bundle and records timestamp
    bundle1 = cag.get_static_cag_bundle()
    assert cag._cached_at is not None
    assert cag._cached_bundle is not None
    first_cached_at = cag._cached_at
    assert bundle1["ttl_seconds"] == 10
    assert "system_prompt" in bundle1
    assert len(bundle1["tools"]) == 1

    # Second fetch within TTL: returns exact cached instance
    bundle2 = cag.get_static_cag_bundle()
    assert bundle2 is bundle1
    assert cag._cached_at == first_cached_at

    # Simulate TTL expiration by backdating _cached_at
    cag._cached_at = datetime.now(timezone.utc) - timedelta(seconds=15)

    # Third fetch after TTL: detects expired cache and recomputes
    bundle3 = cag.get_static_cag_bundle()
    assert bundle3 is not bundle1  # fresh dictionary object
    assert bundle3["cache_hash"] == bundle1["cache_hash"]
    assert cag._cached_at > first_cached_at


def test_cag_alias_get_cag_bundle() -> None:
    """Verify get_cag_bundle alias works interchangeably with get_static_cag_bundle."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=30)

    bundle_alias = cag.get_cag_bundle()
    bundle_static = cag.get_static_cag_bundle()
    assert bundle_alias is bundle_static


def test_cag_invalidate_cache_resets_all_state() -> None:
    """Verify invalidate_cache resets _cached_at, _cached_bundle, and _cache_hash."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=60)

    bundle1 = cag.get_static_cag_bundle()
    assert cag._cached_at is not None
    assert cag._cached_bundle is not None
    assert cag._cache_hash != ""

    cag.invalidate_cache()

    assert getattr(cag, "_cached_at") is None
    assert getattr(cag, "_cached_bundle") is None
    assert cag._cache_hash == ""
    assert cag._cached_content_id is None

    # Recomputing after invalidation succeeds
    bundle2 = cag.get_static_cag_bundle()
    assert bundle2 is not bundle1
    assert cag._cached_at is not None


def test_cag_force_refresh_recomputes_cache() -> None:
    """Verify force_refresh=True ignores valid cache and updates timestamp."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=300)

    bundle1 = cag.get_static_cag_bundle()
    original_time = cag._cached_at
    assert original_time is not None

    bundle_forced = cag.get_static_cag_bundle(force_refresh=True)
    assert bundle_forced is not bundle1
    assert cag._cached_at is not None
    assert cag._cached_at >= original_time


@pytest.mark.asyncio
async def test_cag_sync_gemini_cache_resets_bundle_and_cached_at() -> None:
    """Verify sync_gemini_context_cache resets _cached_bundle and _cached_at upon cache creation."""
    registry = ToolRegistry([SimpleEchoTool()])
    cag = ToolCAGManager(tool_registry=registry, ttl_seconds=1800)

    # Pre-populate in-memory bundle
    cag.get_static_cag_bundle()
    assert cag._cached_bundle is not None
    assert cag._cached_at is not None

    mock_cache = MagicMock()
    mock_cache.name = "cachedContents/gemini_cag_12345"

    mock_client = MagicMock()
    mock_client.aio.caches.create = AsyncMock(return_value=mock_cache)

    result = await cag.sync_gemini_context_cache(client=mock_client)
    assert result == "cachedContents/gemini_cag_12345"
    assert cag._cached_content_id == "cachedContents/gemini_cag_12345"
    # State reset for fresh read with cached_content_id
    assert getattr(cag, "_cached_bundle") is None
    assert getattr(cag, "_cached_at") is None

    # Next get_static_cag_bundle includes cached_content_id
    new_bundle = cag.get_static_cag_bundle()
    assert new_bundle["cached_content_id"] == "cachedContents/gemini_cag_12345"
    assert cag._cached_at is not None
