"""Google OAuth2 Authentication Helper with deterministic offline mock mode."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from tars.config import get_settings

logger = logging.getLogger("tars.tools.google.auth")


class GoogleAuthHelper:
    """Helper managing Google Workspace OAuth2 Access Tokens and Mock Mode."""

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

        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def get_access_token(self) -> str:
        """Obtain a valid OAuth2 access token, renewing via refresh token if necessary.

        Returns:
            str: Valid Bearer access token string.
        """
        if self.mock_mode:
            return "mock_google_oauth2_access_token"

        # Try loading credentials from DB if missing
        if not (self.refresh_token and self.client_id and self.client_secret):
            try:
                from sqlalchemy import select

                from tars.db.models import TARSSettings
                from tars.db.session import get_session_factory

                factory = get_session_factory()
                async with factory() as session:
                    stmt = (
                        select(TARSSettings)
                        .where(
                            (TARSSettings.google_refresh_token.is_not(None))
                            | (TARSSettings.google_client_id.is_not(None))
                        )
                        .order_by(TARSSettings.updated_at.desc())
                        .limit(1)
                    )
                    res = await session.execute(stmt)
                    s = res.scalar_one_or_none()
                    if s:
                        if not self.refresh_token and s.google_refresh_token:
                            self.refresh_token = s.google_refresh_token
                        if not self.client_id and s.google_client_id:
                            self.client_id = s.google_client_id
                        if not self.client_secret and s.google_client_secret:
                            self.client_secret = s.google_client_secret
            except Exception as exc:
                logger.debug("Could not query TARSSettings for Google credentials: %s", exc)

        if not (self.client_id and self.client_secret):
            raise RuntimeError(
                "Google OAuth2 클라이언트 설정(Client ID / Secret)이 누락되었습니다. MCP & TOOLS 설정에서 등록해 주세요."
            )

        if not self.refresh_token:
            raise RuntimeError(
                "Google Workspace 계정이 연동되지 않았습니다. MCP & TOOLS 설정에서 Google 계정을 연동해 주세요."
            )

        now = time.time()
        if self._cached_token and now < (self._token_expires_at - 60):
            return self._cached_token

        client = self._get_http_client()
        token_url = "https://oauth2.googleapis.com/token"
        payload: dict[str, Any] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            resp = await client.post(token_url, data=payload)
            resp.raise_for_status()
            data = resp.json()
            access_token = str(data["access_token"])
            expires_in = int(data.get("expires_in", 3600))
            self._cached_token = access_token
            self._token_expires_at = now + expires_in
            logger.info("Renewed Google OAuth2 access token (expires in %ds)", expires_in)
            return access_token
        except Exception as exc:
            logger.error("Failed to refresh Google OAuth2 access token: %s", exc)
            raise RuntimeError(
                f"Google OAuth2 토큰 갱신에 실패했습니다 ({exc}). MCP & TOOLS 설정에서 계정을 다시 연동해 주세요."
            ) from exc

    async def get_auth_headers(self) -> dict[str, str]:
        """Generate Authorization headers dict for Google API REST requests."""
        token = await self.get_access_token()
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
