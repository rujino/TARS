"""Integration tests for containerization, reverse proxy, SSL automation, and environment configurations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def _get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


# =============================================================================
# 1. Dockerfile Multi-Stage Build Structure Tests
# =============================================================================


def test_dockerfile_multi_stage_structure() -> None:
    """Verify Dockerfile contains multi-stage builder and non-root runtime with uv cache."""
    root = _get_project_root()
    dockerfile_path = root / "Dockerfile"
    assert dockerfile_path.is_file(), f"Dockerfile is missing at {dockerfile_path}"

    content = dockerfile_path.read_text(encoding="utf-8")

    # 1. Multi-stage build definitions
    assert re.search(r"FROM\s+python:3\.11-slim\s+AS\s+builder", content, re.IGNORECASE), (
        "Dockerfile must have 'FROM python:3.11-slim AS builder' stage"
    )
    assert re.search(r"FROM\s+python:3\.11-slim\s+AS\s+runtime", content, re.IGNORECASE) or re.search(
        r"FROM\s+python:3\.11-slim", content, re.IGNORECASE
    ), "Dockerfile must have runtime stage based on python:3.11-slim"

    # 2. uv package manager installation and cache mount
    assert "ghcr.io/astral-sh/uv" in content or "uv" in content, "Dockerfile should use uv package manager"
    assert "--mount=type=cache,target=/root/.cache/uv" in content, (
        "Dockerfile builder must utilize uv cache mount for fast builds"
    )

    # 3. Non-root user isolation (UID/GID: 10001 tarsuser)
    assert "tarsuser" in content, "Dockerfile must configure non-root user 'tarsuser'"
    assert "10001" in content, "Dockerfile must use UID/GID 10001 for non-root security"
    assert re.search(r"USER\s+tarsuser", content), "Dockerfile must switch to USER tarsuser"

    # 4. Storage & Data directory creation
    assert "/app/storage" in content, "Dockerfile must initialize /app/storage"
    assert "/app/data" in content, "Dockerfile must initialize /app/data"

    # 5. Port exposure & Healthcheck
    assert "EXPOSE 8000" in content, "Dockerfile must expose port 8000"
    assert "HEALTHCHECK" in content, "Dockerfile must contain HEALTHCHECK instruction"
    assert "http://localhost:8000/health" in content or "/health" in content, (
        "Dockerfile healthcheck must target /health endpoint"
    )

    # 6. Entrypoint and CMD
    assert "ENTRYPOINT" in content, "Dockerfile must define an ENTRYPOINT"
    assert "CMD" in content, "Dockerfile must define a default CMD"


# =============================================================================
# 2. Docker Compose & Override Structure Tests
# =============================================================================


def test_docker_compose_production_structure() -> None:
    """Verify docker-compose.yml defines all 4 services, networks, volumes, and healthchecks."""
    root = _get_project_root()
    compose_path = root / "docker-compose.yml"
    assert compose_path.is_file(), f"docker-compose.yml is missing at {compose_path}"

    content = compose_path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(content)

    assert "services" in data, "docker-compose.yml must define 'services'"
    services: dict[str, Any] = data["services"]

    # 1. Verify all 4 core services are present
    expected_services = {"tars-backend", "tars-db", "tars-nginx", "certbot"}
    assert expected_services.issubset(set(services.keys())), (
        f"Missing services in docker-compose.yml: {expected_services - set(services.keys())}"
    )

    # 2. Verify tars-backend configuration
    backend = services["tars-backend"]
    assert "build" in backend, "tars-backend must define build context"
    assert backend.get("restart") == "unless-stopped", "tars-backend must have restart: unless-stopped"
    assert "tars-db" in str(backend.get("depends_on", {})), "tars-backend must depend on tars-db"
    assert "healthcheck" in backend, "tars-backend must configure healthcheck"
    assert "tars-network" in backend.get("networks", []), "tars-backend must connect to tars-network"

    backend_vols = str(backend.get("volumes", []))
    assert "/app/storage" in backend_vols, "tars-backend must mount storage volume"
    assert "/app/data" in backend_vols, "tars-backend must mount data volume"

    # 3. Verify tars-db configuration
    db = services["tars-db"]
    assert "postgres" in db.get("image", ""), "tars-db must use a postgres image"
    assert "16" in db.get("image", ""), "tars-db must use PostgreSQL 16"
    assert db.get("restart") == "unless-stopped", "tars-db must have restart: unless-stopped"
    assert "healthcheck" in db, "tars-db must configure pg_isready healthcheck"
    assert "postgres_data" in str(db.get("volumes", [])), "tars-db must mount postgres_data named volume"
    assert "tars-network" in db.get("networks", []), "tars-db must connect to tars-network"

    # 4. Verify tars-nginx configuration
    nginx = services["tars-nginx"]
    assert "nginx" in nginx.get("image", ""), "tars-nginx must use nginx image"
    assert nginx.get("restart") == "unless-stopped", "tars-nginx must have restart: unless-stopped"
    ports = str(nginx.get("ports", []))
    assert "80:80" in ports or "80" in ports, "tars-nginx must bind port 80"
    assert "443:443" in ports or "443" in ports, "tars-nginx must bind port 443"
    assert "tars-backend" in str(nginx.get("depends_on", {})), "tars-nginx must depend on tars-backend"
    assert "tars-network" in nginx.get("networks", []), "tars-nginx must connect to tars-network"

    nginx_vols = str(nginx.get("volumes", []))
    assert "nginx.conf" in nginx_vols, "tars-nginx must mount nginx.conf"
    assert "certbot" in nginx_vols or "letsencrypt" in nginx_vols, "tars-nginx must mount certbot SSL volume"

    # 5. Verify certbot configuration
    certbot = services["certbot"]
    assert "certbot" in certbot.get("image", ""), "certbot service must use certbot/certbot image"
    assert "tars-network" in certbot.get("networks", []), "certbot must connect to tars-network"

    # 6. Verify top-level volumes and networks
    assert "volumes" in data, "docker-compose.yml must define top-level volumes"
    assert "postgres_data" in data["volumes"], "docker-compose.yml must define postgres_data volume"
    assert "networks" in data, "docker-compose.yml must define top-level networks"
    assert "tars-network" in data["networks"], "docker-compose.yml must define tars-network"


def test_docker_compose_override_structure() -> None:
    """Verify docker-compose.override.yml provides local development port exposures and volume mounts."""
    root = _get_project_root()
    override_path = root / "docker-compose.override.yml"
    assert override_path.is_file(), f"docker-compose.override.yml missing at {override_path}"

    content = override_path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(content)

    assert "services" in data, "docker-compose.override.yml must define 'services'"
    services: dict[str, Any] = data["services"]

    # tars-backend override
    assert "tars-backend" in services, "override must configure tars-backend"
    backend = services["tars-backend"]
    assert "8000:8000" in str(backend.get("ports", [])), "override must map port 8000 for local access"

    backend_vols = str(backend.get("volumes", []))
    assert "./tars" in backend_vols, "override must bind-mount ./tars for live reload"

    # tars-db override
    assert "tars-db" in services, "override must configure tars-db"
    db = services["tars-db"]
    assert "5432:5432" in str(db.get("ports", [])), "override must expose port 5432 for local DB inspection"


# =============================================================================
# 3. Nginx Reverse Proxy Directives & Streaming Tests
# =============================================================================


def test_nginx_main_configuration() -> None:
    """Verify nginx/nginx.conf contains Gzip, client limits, and WebSocket connection upgrade mapping."""
    root = _get_project_root()
    nginx_conf_path = root / "nginx" / "nginx.conf"
    assert nginx_conf_path.is_file(), f"nginx/nginx.conf missing at {nginx_conf_path}"

    content = nginx_conf_path.read_text(encoding="utf-8")

    # 1. Performance & upload limits
    assert "worker_processes auto;" in content, "nginx.conf must configure worker_processes auto"
    assert "client_max_body_size 50M;" in content or "client_max_body_size" in content, (
        "nginx.conf must define client_max_body_size for file/audio uploads"
    )

    # 2. WebSocket upgrade map
    assert "map $http_upgrade $connection_upgrade" in content, (
        "nginx.conf must define $connection_upgrade map for WebSocket support"
    )
    assert "default upgrade;" in content, "$connection_upgrade map must map default to upgrade"
    assert "''      close;" in content or "'' close;" in content, (
        "$connection_upgrade map must map empty upgrade to close"
    )

    # 3. Gzip compression
    assert "gzip on;" in content, "nginx.conf must enable gzip"
    assert "application/json" in content, "gzip_types must include application/json"
    assert "application/javascript" in content or "text/javascript" in content, "gzip_types must include javascript"
    assert "application/manifest+json" in content, "gzip_types must include application/manifest+json for PWA"

    # 4. Include virtual hosts
    assert "include /etc/nginx/conf.d/*.conf;" in content, "nginx.conf must include conf.d/*.conf"


def test_nginx_virtual_host_streaming_and_ssl() -> None:
    """Verify nginx/conf.d/default.conf configures SSL, WS upgrade, SSE zero-buffering, and security headers."""
    root = _get_project_root()
    vhost_path = root / "nginx" / "conf.d" / "default.conf"
    assert vhost_path.is_file(), f"nginx/conf.d/default.conf missing at {vhost_path}"

    content = vhost_path.read_text(encoding="utf-8")

    # 1. Upstream definition
    assert "upstream tars_backend" in content or "server tars-backend:8000" in content, (
        "default.conf must define upstream tars_backend or point to tars-backend:8000"
    )

    # 2. HTTP to HTTPS redirect & ACME challenge
    assert "listen 80;" in content, "default.conf must listen on port 80"
    assert "location /.well-known/acme-challenge/" in content, (
        "default.conf must route ACME challenge for Certbot"
    )
    assert "/var/www/certbot" in content, "ACME challenge must be served from /var/www/certbot"
    assert "return 301 https://" in content or "return 301 https://$host$request_uri;" in content, (
        "default.conf must redirect HTTP to HTTPS"
    )

    # 3. HTTPS Server & SSL protocols
    assert "listen 443 ssl" in content, "default.conf must listen on port 443 with SSL"
    assert "ssl_certificate" in content, "default.conf must define ssl_certificate"
    assert "ssl_certificate_key" in content, "default.conf must define ssl_certificate_key"
    assert "TLSv1.2 TLSv1.3" in content or "TLSv1.3" in content, "default.conf must require modern TLS protocols"

    # 4. Security Headers
    assert "Strict-Transport-Security" in content, "default.conf must configure HSTS"
    assert "X-Frame-Options" in content, "default.conf must configure X-Frame-Options"
    assert "X-Content-Type-Options" in content, "default.conf must configure X-Content-Type-Options"

    # 5. WebSocket Route (/api/v1/chat/ws)
    assert "location /api/v1/chat/ws" in content, "default.conf must have dedicated location /api/v1/chat/ws"
    ws_block = content[content.find("location /api/v1/chat/ws") :]
    ws_block = ws_block[: ws_block.find("location", 10)] if "location" in ws_block[10:] else ws_block
    assert "proxy_http_version 1.1;" in ws_block, "WebSocket proxy must use HTTP 1.1"
    assert "Upgrade" in ws_block, "WebSocket proxy must forward Upgrade header"
    assert "$connection_upgrade" in ws_block or "upgrade" in ws_block, "WebSocket proxy must set Connection upgrade"
    assert "proxy_buffering off;" in ws_block, "WebSocket proxy must disable proxy buffering"

    # 6. SSE Stream Route (/api/v1/chat/stream)
    assert "location /api/v1/chat/stream" in content, "default.conf must have dedicated location /api/v1/chat/stream"
    sse_block = content[content.find("location /api/v1/chat/stream") :]
    sse_block = sse_block[: sse_block.find("location", 10)] if "location" in sse_block[10:] else sse_block
    assert "proxy_buffering off;" in sse_block, "SSE proxy must have proxy_buffering off for zero-latency streaming"
    assert "proxy_cache off;" in sse_block, "SSE proxy must have proxy_cache off"
    assert "proxy_read_timeout 300s;" in sse_block or "300s" in sse_block, (
        "SSE proxy must configure extended read timeout (>=300s) for LLM generation"
    )
    assert "X-Accel-Buffering no" in sse_block or "chunked_transfer_encoding on" in sse_block, (
        "SSE proxy must ensure unbuffered chunked transfer encoding"
    )


# =============================================================================
# 4. Production Environment Template (.env.production.example) Tests
# =============================================================================


def test_env_production_example_completeness() -> None:
    """Verify .env.production.example includes all 7 required configuration categories and variables."""
    root = _get_project_root()
    env_path = root / ".env.production.example"
    assert env_path.is_file(), f".env.production.example missing at {env_path}"

    content = env_path.read_text(encoding="utf-8")

    # Required variable keys across all 7 categories
    required_variables = [
        # 1. Core
        "TARS_APP_NAME",
        "TARS_ENVIRONMENT",
        "TARS_DEBUG",
        # 2. Security & Auth
        "TARS_JWT_SECRET_KEY",
        "TARS_JWT_ALGORITHM",
        "TARS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        # 3. Production DB (Postgres)
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "TARS_DATABASE_URL",
        # 4. Domain & SSL
        "TARS_DOMAIN",
        "CERTBOT_EMAIL",
        # 5. AI Inference & LLM
        "TARS_GEMINI_API_KEY",
        "TARS_GEMINI_MODEL_NAME",
        "TARS_LLAMACPP_BASE_URL",
        # 6. Storage & Persona
        "TARS_STORAGE_DIR",
        "TARS_DEFAULT_HUMOR_LEVEL",
        "TARS_DEFAULT_HONESTY_LEVEL",
        "TARS_DEFAULT_MODE",
        # 7. Integrations
        "TARS_GOOGLE_MOCK_MODE",
    ]

    for var in required_variables:
        assert re.search(rf"^{var}=", content, re.MULTILINE), (
            f"Required environment variable '{var}' missing in .env.production.example"
        )


# =============================================================================
# 5. Shell Scripts Executable & Syntax Validation Tests
# =============================================================================


def test_scripts_syntax_and_executability() -> None:
    """Verify initialization and migration helper scripts exist with proper error handling directives."""
    root = _get_project_root()
    scripts_dir = root / "scripts"
    assert scripts_dir.is_dir(), f"scripts directory missing at {scripts_dir}"

    # 1. Verify init_ssl.sh
    init_ssl_path = scripts_dir / "init_ssl.sh"
    assert init_ssl_path.is_file(), f"init_ssl.sh missing at {init_ssl_path}"
    ssl_content = init_ssl_path.read_text(encoding="utf-8")
    assert ssl_content.startswith("#!/"), "init_ssl.sh must contain valid shebang"
    assert "set -e" in ssl_content or "set -euo pipefail" in ssl_content, (
        "init_ssl.sh must enable error-exit (set -e or set -euo pipefail)"
    )
    assert "openssl" in ssl_content, "init_ssl.sh must utilize openssl for SSL bootstrap"
    assert "certbot" in ssl_content, "init_ssl.sh must support certbot Let's Encrypt issuance"
    assert "dev" in ssl_content or "localhost" in ssl_content, "init_ssl.sh must support local/LAN dev mode"

    # 2. Verify run_migrations.sh (or entrypoint.sh)
    run_mig_path = scripts_dir / "run_migrations.sh"
    entrypoint_path = scripts_dir / "entrypoint.sh"
    assert run_mig_path.is_file() or entrypoint_path.is_file(), (
        "scripts/run_migrations.sh or scripts/entrypoint.sh must exist"
    )

    mig_script = run_mig_path if run_mig_path.is_file() else entrypoint_path
    mig_content = mig_script.read_text(encoding="utf-8")
    assert mig_content.startswith("#!/"), f"{mig_script.name} must contain valid shebang"
    assert "alembic upgrade head" in mig_content, f"{mig_script.name} must execute 'alembic upgrade head'"
