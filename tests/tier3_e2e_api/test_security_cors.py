"""Tier 3 E2E API Tests: CORS Whitelist Configuration and Security (SEC-01).

Verifies:
1. Allowed origins from Settings.cors_origins receive:
   - Access-Control-Allow-Origin: <matching_origin>
   - Access-Control-Allow-Credentials: true
2. Disallowed / untrusted origins do not receive Access-Control-Allow-Origin.
3. Preflight OPTIONS requests for allowed origins succeed with proper headers.
4. Preflight OPTIONS requests for disallowed origins do not expose CORS permissions.
5. Dynamic customization of cors_origins in Settings is respected.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from tars.api.app import create_app
from tars.config import Settings


@pytest.mark.asyncio
async def test_cors_allowed_origin_simple_request() -> None:
    """Verify that requests from a whitelisted origin receive correct CORS headers."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Request from default allowed origin
        response = await client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_cors_all_default_whitelisted_origins() -> None:
    """Verify all default whitelisted origins in Settings are accepted."""
    app = create_app()
    transport = ASGITransport(app=app)
    expected_origins = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for origin in expected_origins:
            response = await client.get(
                "/health",
                headers={"Origin": origin},
            )
            assert response.status_code == 200
            assert response.headers.get("access-control-allow-origin") == origin
            assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_cors_disallowed_origin_rejected() -> None:
    """Verify that untrusted/disallowed origins do NOT receive allow-origin headers."""
    app = create_app()
    transport = ASGITransport(app=app)
    disallowed_origins = [
        "http://evil-attacker.com",
        "https://malicious-site.org",
        "http://localhost:9000",
        "http://192.168.1.100:3000",
    ]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for origin in disallowed_origins:
            response = await client.get(
                "/health",
                headers={"Origin": origin},
            )
            assert response.status_code == 200
            # CORS middleware must not reflect or allow untrusted origin
            assert response.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_cors_preflight_options_allowed_origin() -> None:
    """Verify preflight OPTIONS request returns 200 with allowed methods and headers."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/chat/stream",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert "POST" in response.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_cors_preflight_options_disallowed_origin() -> None:
    """Verify preflight OPTIONS request for untrusted origin does not return CORS headers."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/chat/stream",
            headers={
                "Origin": "https://attacker.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        # For disallowed origins, CORSMiddleware does not include access-control-allow-origin
        assert response.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_cors_custom_origins_configuration() -> None:
    """Verify that configuring custom cors_origins in Settings takes effect."""
    custom_settings = Settings(
        cors_origins=["https://tars.company.internal", "https://app.tars.ai"]
    )
    with patch("tars.api.app.get_settings", return_value=custom_settings):
        custom_app = create_app()
        transport = ASGITransport(app=custom_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Custom origin allowed
            res_allowed = await client.get(
                "/health",
                headers={"Origin": "https://app.tars.ai"},
            )
            assert res_allowed.headers.get("access-control-allow-origin") == "https://app.tars.ai"
            assert res_allowed.headers.get("access-control-allow-credentials") == "true"

            # Default localhost origin now rejected since it is not in the custom whitelist
            res_rejected = await client.get(
                "/health",
                headers={"Origin": "http://localhost:3000"},
            )
            assert res_rejected.headers.get("access-control-allow-origin") is None
