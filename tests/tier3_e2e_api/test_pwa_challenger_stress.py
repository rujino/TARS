"""Empirical Challenger Adversarial Stress Test Suite for PWA & Static Serving.

This module stress-tests:
1. Security & Path Traversal Prevention
2. Strict MIME Type / Content-Type Header Verification
3. iOS Safari PWA Contract & HTML DOM Structure Verification
4. Web App Manifest Schema & Icon Resolvability
5. Service Worker Asset Resolvability & Caching Strategy Verification
6. HTTP Method Restrictions (405 Method Not Allowed)
7. Non-existent Routes & 404 Error Handling
8. Full API / Static Router Coexistence
9. High Concurrency & Burst Stress Testing
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from httpx import AsyncClient

# ==============================================================================
# 1. Security & Path Traversal Attacks
# ==============================================================================


@pytest.mark.asyncio
async def test_path_traversal_attempts_are_blocked(api_client: AsyncClient) -> None:
    """Verify directory traversal attempts cannot access server-side source files or system files."""
    traversal_payloads = [
        "/static/../main.py",
        "/static/..%2fmain.py",
        "/static/....//main.py",
        "/static/%2e%2e/%2e%2e/pyproject.toml",
        "/static/../tars/config.py",
        "/static/%2e%2e/tars/config.py",
        "/static/../../../../etc/passwd",
        "/static/etc/passwd",
        "/static/..\\..\\main.py",
    ]
    for payload in traversal_payloads:
        resp = await api_client.get(payload)
        # Starlette StaticFiles returns 404 for paths outside root directory
        assert resp.status_code in (400, 404), f"Payload {payload} returned {resp.status_code}"
        assert "create_app" not in resp.text
        assert "jwt_secret_key" not in resp.text


# ==============================================================================
# 2. Strict MIME Type & Content-Type Headers
# ==============================================================================


@pytest.mark.asyncio
async def test_strict_content_type_headers(api_client: AsyncClient) -> None:
    """Verify exact Content-Type headers for all PWA and static entrypoints."""
    # Root index.html
    root_resp = await api_client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.headers["content-type"].startswith("text/html")

    # Manifest JSON
    manifest_resp = await api_client.get("/manifest.json")
    assert manifest_resp.status_code == 200
    assert manifest_resp.headers["content-type"].startswith("application/manifest+json")

    # Service Worker JS
    sw_resp = await api_client.get("/sw.js")
    assert sw_resp.status_code == 200
    assert sw_resp.headers["content-type"].startswith("application/javascript")

    # CSS files
    for css_file in ["style.css", "hud.css", "components.css"]:
        resp = await api_client.get(f"/static/css/{css_file}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css"), f"Failed for {css_file}"

    # JS files
    for js_file in [
        "app.js",
        "api.js",
        "chat.js",
        "tts.js",
        "vendor/marked.min.js",
        "vendor/purify.min.js",
    ]:
        resp = await api_client.get(f"/static/js/{js_file}")
        assert resp.status_code == 200
        ct = resp.headers["content-type"]
        assert "javascript" in ct or "text/javascript" in ct, f"Failed for {js_file}: {ct}"

    # Icons
    for icon_file in ["icon-192.png", "icon-512.png", "apple-touch-icon.png"]:
        resp = await api_client.get(f"/static/icons/{icon_file}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/png"), f"Failed for {icon_file}"
        assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


# ==============================================================================
# 3. HTML5 & iOS Safari PWA Requirements
# ==============================================================================


@pytest.mark.asyncio
async def test_html5_structure_and_ios_meta_tags(api_client: AsyncClient) -> None:
    """Verify HTML5 structure, iOS PWA meta tags, and critical DOM elements."""
    resp = await api_client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # HTML5 Doctype & lang
    assert html.lstrip().startswith("<!DOCTYPE html>") or html.lstrip().startswith(
        "<!doctype html>"
    )
    assert '<html lang="en">' in html

    # Meta tags for iOS & PWA
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
    assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in html
    assert '<meta name="apple-mobile-web-app-title" content="TARS">' in html
    assert '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">' in html
    assert '<link rel="manifest" href="/manifest.json">' in html
    assert "viewport-fit=cover" in html
    assert "user-scalable=no" in html

    # Essential UI HUD DOM elements
    required_ids = [
        "app",
        "status-dot",
        "status-text",
        "mode-badge",
        "btn-tts",
        "btn-config",
        "btn-logout",
        "auth-view",
        "tab-login",
        "tab-signup",
        "form-login",
        "form-signup",
        "chat-view",
        "sidebar",
        "user-display-name",
        "humor-slider",
        "honesty-slider",
        "mode-companion",
        "mode-work",
        "btn-reset-config",
        "messages-container",
        "chat-input",
        "send-btn",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html, f"Missing required DOM element: id='{element_id}'"


# ==============================================================================
# 4. Manifest JSON Schema & Icon Resolvability
# ==============================================================================


@pytest.mark.asyncio
async def test_manifest_schema_and_icons_resolvable(api_client: AsyncClient) -> None:
    """Verify Web App Manifest schema fields and that every icon URL is 200 OK."""
    resp = await api_client.get("/manifest.json")
    assert resp.status_code == 200
    manifest: dict[str, Any] = resp.json()

    assert manifest.get("name") == "TARS - Tactical Autonomous Robotic System"
    assert manifest.get("short_name") == "TARS"
    assert manifest.get("start_url") == "/"
    assert manifest.get("scope") == "/"
    assert manifest.get("display") == "standalone"
    assert manifest.get("orientation") == "portrait-primary"
    assert manifest.get("background_color") == "#08080a"
    assert manifest.get("theme_color") == "#08080a"
    assert "description" in manifest

    icons = manifest.get("icons", [])
    assert isinstance(icons, list)
    assert len(icons) >= 3

    # Check each icon in manifest is resolvable via GET
    for icon in icons:
        src = icon.get("src")
        assert src, f"Icon missing src: {icon}"
        icon_resp = await api_client.get(src)
        assert icon_resp.status_code == 200, f"Icon {src} returned {icon_resp.status_code}"
        assert icon_resp.content.startswith(b"\x89PNG\r\n\x1a\n")


# ==============================================================================
# 5. Service Worker Pre-cache Assets 100% Resolvability
# ==============================================================================


@pytest.mark.asyncio
async def test_service_worker_precache_assets_all_exist(api_client: AsyncClient) -> None:
    """Verify every asset listed in sw.js ASSETS_TO_CACHE returns 200 OK."""
    sw_resp = await api_client.get("/sw.js")
    assert sw_resp.status_code == 200
    sw_code = sw_resp.text

    # Extract ASSETS_TO_CACHE array from sw.js
    match = re.search(r"const\s+ASSETS_TO_CACHE\s*=\s*\[(.*?)\];", sw_code, re.DOTALL)
    assert match is not None, "Could not find ASSETS_TO_CACHE in sw.js"

    raw_assets = match.group(1)
    asset_urls = [
        line.strip().strip(",").strip("'").strip('"')
        for line in raw_assets.split("\n")
        if line.strip() and not line.strip().startswith("//")
    ]
    # Filter out empty entries
    asset_urls = [u for u in asset_urls if u]
    assert len(asset_urls) >= 10, f"Expected at least 10 cached assets, got {len(asset_urls)}"

    # Test each cached asset endpoint
    for url in asset_urls:
        resp = await api_client.get(url)
        assert resp.status_code == 200, (
            f"SW precache asset '{url}' returned status {resp.status_code}"
        )
        assert len(resp.content) > 0, f"SW precache asset '{url}' returned empty body"


# ==============================================================================
# 6. HTTP Method Restrictions (405 Method Not Allowed)
# ==============================================================================


@pytest.mark.asyncio
async def test_http_method_restrictions_on_static_routes(api_client: AsyncClient) -> None:
    """Verify that non-GET methods on root, manifest, and sw return 405."""
    routes = ["/", "/manifest.json", "/sw.js"]
    disallowed_methods = ["post", "put", "delete", "patch"]

    for route in routes:
        for method_name in disallowed_methods:
            method = getattr(api_client, method_name)
            resp = await method(route)
            assert resp.status_code == 405, (
                f"{method_name.upper()} {route} returned {resp.status_code} (expected 405)"
            )


# ==============================================================================
# 7. Non-existent Routes & 404 Handling
# ==============================================================================


@pytest.mark.asyncio
async def test_nonexistent_routes_return_404(api_client: AsyncClient) -> None:
    """Verify nonexistent paths return 404 without leaking server info."""
    nonexistent_paths = [
        "/static/nonexistent_xyz_123.js",
        "/static/css/nonexistent.css",
        "/static/icons/missing.png",
        "/nonexistent_route_tars_abc",
        "/api/v1/nonexistent_endpoint",
    ]
    for path in nonexistent_paths:
        resp = await api_client.get(path)
        assert resp.status_code == 404, f"Path {path} returned {resp.status_code} (expected 404)"


# ==============================================================================
# 8. API Router Coexistence & Conflict Check
# ==============================================================================


@pytest.mark.asyncio
async def test_api_routes_coexistence_and_behavior(api_client: AsyncClient) -> None:
    """Verify that all API routes work correctly and are not shadowed by static files."""
    # Health route
    health_resp = await api_client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok", "app": "TARS"}

    # Auth endpoints
    login_resp = await api_client.post(
        "/api/v1/auth/login",
        json={"username": "nonexistent_operator", "password": "wrongpassword123"},
    )
    assert login_resp.status_code in (400, 401, 422)

    # Protected routes return 401 (not 404 or index.html)
    me_resp = await api_client.get("/api/v1/auth/me")
    assert me_resp.status_code == 401

    config_resp = await api_client.get("/api/v1/tars/config")
    assert config_resp.status_code == 401

    msg_resp = await api_client.post(
        "/api/v1/chat/stream",
        json={"message": "hello"},
    )
    assert msg_resp.status_code == 401


# ==============================================================================
# 9. Concurrency & Burst Stress Testing
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_static_requests(api_client: AsyncClient) -> None:
    """Stress-test static file serving under 100 concurrent requests."""
    endpoints = [
        "/",
        "/manifest.json",
        "/sw.js",
        "/static/css/style.css",
        "/static/css/hud.css",
        "/static/css/components.css",
        "/static/js/app.js",
        "/static/js/api.js",
        "/static/icons/icon-192.png",
        "/health",
    ]

    async def fetch(path: str) -> int:
        resp = await api_client.get(path)
        return resp.status_code

    # 10 endpoints * 10 iterations = 100 concurrent requests
    tasks = [fetch(ep) for ep in endpoints for _ in range(10)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 100
    assert all(code == 200 for code in results), f"Some concurrent requests failed: {set(results)}"
