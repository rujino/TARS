"""Google OAuth2 Authentication Helper with deterministic offline mock mode."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from tars.config import get_settings

logger = logging.getLogger("tars.tools.google.auth")


class GoogleAuthHelper:
    """Helper managing Google Workspace OAuth2 Access Tokens with multi-tenant user isolation and mock mode."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        mock_mode: bool | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self.client_id = client_id or settings.google_client_id
        self.client_secret = client_secret or settings.google_client_secret
        self.refresh_token = refresh_token or settings.google_refresh_token
        self._http_client = http_client
        self._owns_http_client = http_client is None

        # Determine mock mode: explicit flag -> env var -> config
        env_mock = os.environ.get("TARS_GOOGLE_MOCK_MODE", "").lower() in ("true", "1", "yes")
        if mock_mode is not None:
            self.mock_mode = mock_mode
        elif env_mock:
            self.mock_mode = True
        elif settings.google_mock_mode:
            self.mock_mode = True
        else:
            self.mock_mode = False

        # Multi-tenant per-user token cache: user_id -> (access_token, expires_at)
        self._user_token_cache: dict[str, tuple[str, float]] = {}
        # Single-user / test fallback cache
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        # Per-user async locks to prevent thundering-herd token refresh
        self._user_locks: dict[str, asyncio.Lock] = {}

    def _get_user_lock(self, user_id: str | None) -> asyncio.Lock:
        key = user_id or "__default__"
        if key not in self._user_locks:
            self._user_locks[key] = asyncio.Lock()
        return self._user_locks[key]

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    def invalidate_user_cache(self, user_id: str) -> None:
        """Evict cached token for a specific user upon disconnect or token change."""
        self._user_token_cache.pop(user_id, None)
        self._user_locks.pop(user_id, None)

    async def get_access_token(self, user_id: str | None = None) -> str:
        """Obtain a valid OAuth2 access token for the given user, renewing via refresh token if necessary.

        Args:
            user_id: Optional user ID for multi-tenant isolation. If provided, strictly fetches
                     and caches credentials belonging only to this user.

        Returns:
            str: Valid Bearer access token string.
        """
        if self.mock_mode:
            return "mock_google_oauth2_access_token"

        now = time.time()

        # 1. Fast-path check without acquiring lock
        if user_id:
            cached = self._user_token_cache.get(user_id)
            if cached and now < (cached[1] - 60):
                return cached[0]
        else:
            if self._cached_token and now < (self._token_expires_at - 60):
                return self._cached_token

        # 2. Acquire per-user lock to serialize renewal and prevent race conditions
        lock = self._get_user_lock(user_id)
        async with lock:
            now = time.time()
            # Double-check inside lock
            if user_id:
                cached = self._user_token_cache.get(user_id)
                if cached and now < (cached[1] - 60):
                    return cached[0]
            else:
                if self._cached_token and now < (self._token_expires_at - 60):
                    return self._cached_token

            effective_client_id = self.client_id
            effective_client_secret = self.client_secret
            effective_refresh_token = self.refresh_token

            if user_id:
                # Strict DB lookup for this specific user only
                try:
                    from sqlalchemy import select

                    from tars.db.models import TARSSettings
                    from tars.db.session import get_session_factory

                    factory = get_session_factory()
                    async with factory() as session:
                        stmt = select(TARSSettings).where(TARSSettings.user_id == user_id)
                        res = await session.execute(stmt)
                        s = res.scalar_one_or_none()

                        if not s or not (s.google_refresh_token or s.google_access_token or s.google_mock_linked):
                            raise RuntimeError(
                                f"Google Workspace 계정이 연동되지 않았습니다. [MCP & TOOLS]에서 Google 계정을 연동해 주세요."
                            )

                        if s.google_mock_linked:
                            return "mock_google_oauth2_access_token"

                        effective_refresh_token = s.google_refresh_token
                        if not effective_client_id and s.google_client_id:
                            effective_client_id = s.google_client_id
                        if not effective_client_secret and s.google_client_secret:
                            effective_client_secret = s.google_client_secret
                except RuntimeError:
                    raise
                except Exception as exc:
                    logger.error("Could not query TARSSettings for user %s: %s", user_id, exc)
                    raise RuntimeError(
                        f"사용자 Google 계정 설정을 불러오는데 실패했습니다: {exc}"
                    ) from exc

            if not (effective_client_id and effective_client_secret):
                raise RuntimeError(
                    "Google OAuth2 클라이언트 설정(Client ID / Secret)이 누락되었습니다. 관리자에게 문의하거나 설정을 확인해 주세요."
                )

            if not effective_refresh_token:
                raise RuntimeError(
                    "Google Workspace 계정이 연동되지 않았습니다. [MCP & TOOLS]에서 Google 계정을 연동해 주세요."
                )

            # Exchange refresh token for new access token
            client = self._get_http_client()
            token_url = "https://oauth2.googleapis.com/token"
            payload: dict[str, Any] = {
                "client_id": effective_client_id,
                "client_secret": effective_client_secret,
                "refresh_token": effective_refresh_token,
                "grant_type": "refresh_token",
            }

            try:
                resp = await client.post(token_url, data=payload)
                resp.raise_for_status()
                data = resp.json()
                access_token = str(data["access_token"])
                expires_in = int(data.get("expires_in", 3600))

                if user_id:
                    self._user_token_cache[user_id] = (access_token, now + expires_in)
                else:
                    self._cached_token = access_token
                    self._token_expires_at = now + expires_in

                logger.info("Renewed Google OAuth2 access token for user %s (expires in %ds)", user_id or "default", expires_in)
                return access_token
            except Exception as exc:
                logger.error("Failed to refresh Google OAuth2 access token for user %s: %s", user_id or "default", exc)
                raise RuntimeError(
                    f"Google OAuth2 토큰 갱신에 실패했습니다 ({exc}). [MCP & TOOLS] 설정에서 계정을 다시 연동해 주세요."
                ) from exc

    async def get_auth_headers(self, user_id: str | None = None) -> dict[str, str]:
        """Generate Authorization headers dict for Google API REST requests.

        Args:
            user_id: Optional user ID for multi-tenant isolation.
        """
        token = await self.get_access_token(user_id=user_id)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def close(self) -> None:
        """Close resources."""
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def aclose(self) -> None:
        """Alias for close."""
        await self.close()


__all__ = [
    "GoogleAuthHelper",
]
