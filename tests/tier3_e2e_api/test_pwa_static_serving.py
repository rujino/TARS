"""Tier 3 E2E API Tests: PWA Static File Serving, Web Manifest & iOS Compatibility.

Verifies:
1. Static Serving Routes:
   - Root index.html (`GET /`)
   - Web App Manifest (`GET /manifest.json`)
   - Service Worker script (`GET /sw.js`)
   - Static CSS and JS assets (`GET /static/...`)
2. PWA Meta Tags & iOS Standalone Optimization:
   - apple-mobile-web-app-capable
   - apple-mobile-web-app-status-bar-style
   - viewport-fit=cover
3. Manifest JSON Schema Integrity:
   - name, short_name, start_url, display: standalone, icons (192, 512)
4. Non-Interference with existing /api/v1 endpoints.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_index_html_serving(api_client: AsyncClient) -> None:
    """Verify GET / returns 200 OK with text/html and contains core PWA DOM elements."""
    response = await api_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    html_text = response.text
    assert "<!DOCTYPE html>" in html_text or "<!doctype html>" in html_text
    assert "TARS" in html_text
    # Verify viewport and app container
    assert "viewport" in html_text
    assert (
        'id="app"' in html_text
        or 'class="hud-container"' in html_text
        or 'id="chat-container"' in html_text
    )


@pytest.mark.asyncio
async def test_manifest_json_serving(api_client: AsyncClient) -> None:
    """Verify GET /manifest.json returns 200 OK with valid JSON schema."""
    response = await api_client.get("/manifest.json")
    assert response.status_code == 200
    assert "json" in response.headers.get("content-type", "")

    manifest: dict[str, Any] = response.json()
    assert "name" in manifest
    assert "short_name" in manifest
    assert manifest.get("display") == "standalone"
    assert manifest.get("start_url") in ("/", "/index.html", ".")
    assert "icons" in manifest
    assert isinstance(manifest["icons"], list)
    assert len(manifest["icons"]) >= 1


@pytest.mark.asyncio
async def test_service_worker_js_serving(api_client: AsyncClient) -> None:
    """Verify GET /sw.js returns 200 OK with javascript content and lifecycle listeners."""
    response = await api_client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "")

    sw_content = response.text
    assert "addEventListener" in sw_content
    assert "install" in sw_content
    assert "fetch" in sw_content


@pytest.mark.asyncio
async def test_static_assets_css_and_js(api_client: AsyncClient) -> None:
    """Verify static CSS and JavaScript files are served correctly."""
    # Test CSS
    css_resp = await api_client.get("/static/css/style.css")
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.headers.get("content-type", "")

    hud_css_resp = await api_client.get("/static/css/hud.css")
    assert hud_css_resp.status_code == 200
    assert "text/css" in hud_css_resp.headers.get("content-type", "")

    comp_css_resp = await api_client.get("/static/css/components.css")
    assert comp_css_resp.status_code == 200
    assert "text/css" in comp_css_resp.headers.get("content-type", "")

    # Test JS
    js_resp = await api_client.get("/static/js/app.js")
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.headers.get("content-type", "")

    api_js_resp = await api_client.get("/static/js/api.js")
    assert api_js_resp.status_code == 200
    assert "javascript" in api_js_resp.headers.get("content-type", "")

    chat_js_resp = await api_client.get("/static/js/chat.js")
    assert chat_js_resp.status_code == 200
    assert "javascript" in chat_js_resp.headers.get("content-type", "")

    tts_js_resp = await api_client.get("/static/js/tts.js")
    assert tts_js_resp.status_code == 200
    assert "javascript" in tts_js_resp.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_static_asset_not_found_returns_404(
    api_client: AsyncClient,
) -> None:
    """Verify requesting a nonexistent static file returns 404 Not Found."""
    response = await api_client.get("/static/nonexistent_file_tars_xyz.unknown")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pwa_html_ios_meta_tags(api_client: AsyncClient) -> None:
    """Verify HTML contains all required iOS Safari PWA meta tags."""
    response = await api_client.get("/")
    assert response.status_code == 200
    html_text = response.text.lower()

    # Check iOS PWA tags
    assert 'name="apple-mobile-web-app-capable"' in html_text
    assert 'content="yes"' in html_text
    assert 'name="apple-mobile-web-app-status-bar-style"' in html_text
    assert 'rel="manifest"' in html_text
    assert 'rel="apple-touch-icon"' in html_text
    assert "viewport-fit=cover" in html_text
    assert "user-scalable=no" in html_text


@pytest.mark.asyncio
async def test_manifest_json_icons_and_theme(api_client: AsyncClient) -> None:
    """Verify manifest.json contains valid icons (192, 512) and theme colors."""
    response = await api_client.get("/manifest.json")
    assert response.status_code == 200
    manifest: dict[str, Any] = response.json()

    assert "theme_color" in manifest
    assert "background_color" in manifest

    icons = manifest.get("icons", [])
    assert isinstance(icons, list)
    icon_sizes = [str(icon.get("sizes", "")) for icon in icons if isinstance(icon, dict)]
    # Must support at least standard PWA icon sizes
    assert any("192" in s for s in icon_sizes)
    assert any("512" in s for s in icon_sizes)


@pytest.mark.asyncio
async def test_api_routes_not_shadowed_by_static_mount(
    api_client: AsyncClient,
) -> None:
    """Verify API endpoints are not shadowed or blocked by static file mounts."""
    # Health check
    health_resp = await api_client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json().get("status") == "ok"

    # Protected API routes return 401 (not 404 or index.html)
    me_resp = await api_client.get("/api/v1/auth/me")
    assert me_resp.status_code == 401

    config_resp = await api_client.get("/api/v1/tars/config")
    assert config_resp.status_code == 401
