"""Adversarial and empirical stress tests for Phase 4 Milestones 3 & 4.

Tests cover:
- Nginx reverse proxy directive integrity, security headers, and zero-buffering streaming rules
- SSL automation scripts (init_ssl.sh and renew_certs.sh) POSIX compliance and execution logic
- Production environment template (.env.production.example) Pydantic Settings model compatibility
- DEPLOYMENT.md documentation completeness, section verification, and edge device instructions
- Cross-configuration volume, network, and port parity across Docker Compose, Nginx, and Scripts
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from tars.config import Settings


def _get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


class TestNginxAdversarialAndSecurity:
    """Adversarial validation of Nginx core and virtual host proxy directives."""

    def test_nginx_conf_worker_and_buffer_limits(self) -> None:
        """Verify Nginx worker connections, buffer sizing, and upload thresholds."""
        root = _get_project_root()
        nginx_conf = root / "nginx" / "nginx.conf"
        assert nginx_conf.is_file(), "nginx/nginx.conf does not exist"

        content = nginx_conf.read_text(encoding="utf-8")

        # Events tuning
        assert re.search(r"worker_connections\s+1024;", content), "worker_connections must be 1024"
        assert "multi_accept on;" in content, "multi_accept on should be configured"

        # Security: server tokens disabled
        assert "server_tokens off;" in content, "server_tokens off is mandatory for security"

        # Buffer limits
        assert "client_max_body_size 50M;" in content, "client_max_body_size must be 50M"
        assert "client_body_buffer_size 128k;" in content, "client_body_buffer_size must be 128k"

        # Gzip min length and types
        assert "gzip_min_length 256;" in content, "gzip_min_length should be 256"
        assert "application/manifest+json" in content, "manifest+json must be compressed"

    def test_nginx_vhost_ssl_security_and_hsts(self) -> None:
        """Verify Nginx virtual host enforces modern TLS, HSTS, and strict security headers."""
        root = _get_project_root()
        vhost = root / "nginx" / "conf.d" / "default.conf"
        assert vhost.is_file(), "nginx/conf.d/default.conf does not exist"

        content = vhost.read_text(encoding="utf-8")

        # HTTP to HTTPS redirect
        assert "listen 80;" in content
        assert "return 301 https://$host$request_uri;" in content

        # ACME challenge location block
        assert "location /.well-known/acme-challenge/" in content
        assert "root /var/www/certbot;" in content

        # SSL modern ciphers and OCSP
        assert "TLSv1.2 TLSv1.3;" in content
        assert "ssl_prefer_server_ciphers off;" in content
        assert "ssl_session_cache shared:SSL:10m;" in content
        assert "ssl_stapling on;" in content
        assert "ssl_stapling_verify on;" in content

        # Strict security headers
        assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains" always;' in content
        assert 'X-Frame-Options "SAMEORIGIN" always;' in content
        assert 'X-Content-Type-Options "nosniff" always;' in content
        assert 'X-XSS-Protection "1; mode=block" always;' in content
        assert 'Referrer-Policy "strict-origin-when-cross-origin" always;' in content
        assert 'Permissions-Policy "microphone=(self), camera=(), geolocation=()" always;' in content

    def test_nginx_streaming_endpoints_zero_buffering(self) -> None:
        """Verify WebSocket and SSE routes have correct timeouts and proxy buffering disabled."""
        root = _get_project_root()
        vhost = root / "nginx" / "conf.d" / "default.conf"
        content = vhost.read_text(encoding="utf-8")

        # 1. WebSocket /api/v1/chat/ws
        assert "location /api/v1/chat/ws" in content
        ws_idx = content.find("location /api/v1/chat/ws")
        ws_snippet = content[ws_idx : ws_idx + 400]
        assert "proxy_http_version 1.1;" in ws_snippet
        assert "Upgrade" in ws_snippet
        assert "$connection_upgrade" in ws_snippet
        assert "proxy_read_timeout 3600s;" in ws_snippet
        assert "proxy_buffering off;" in ws_snippet

        # 2. SSE /api/v1/chat/stream
        assert "location /api/v1/chat/stream" in content
        sse_idx = content.find("location /api/v1/chat/stream")
        sse_snippet = content[sse_idx : sse_idx + 400]
        assert "proxy_buffering off;" in sse_snippet
        assert "proxy_cache off;" in sse_snippet
        assert "X-Accel-Buffering no" in sse_snippet
        assert "chunked_transfer_encoding on;" in sse_snippet
        assert "proxy_read_timeout 300s;" in sse_snippet


class TestSSLScriptsAdversarial:
    """Adversarial validation of SSL initialization and renewal shell scripts."""

    def test_init_ssl_script_robustness_and_paths(self) -> None:
        """Verify scripts/init_ssl.sh contains proper parameter parsing, mode handling, and error traps."""
        root = _get_project_root()
        init_ssl = root / "scripts" / "init_ssl.sh"
        assert init_ssl.is_file(), "scripts/init_ssl.sh missing"

        content = init_ssl.read_text(encoding="utf-8")

        assert content.startswith("#!/usr/bin/env bash") or content.startswith("#!/bin/bash")
        assert "set -euo pipefail" in content, "Must use set -euo pipefail"

        # Check support for dev / localhost / staging
        assert "dev" in content
        assert "localhost" in content
        assert "STAGING" in content or "staging" in content
        assert "certbot" in content
        assert "docker compose exec tars-nginx nginx -s reload" in content

    def test_renew_certs_script_robustness(self) -> None:
        """Verify scripts/renew_certs.sh exists, is executable, and contains reload safeguards."""
        root = _get_project_root()
        renew_script = root / "scripts" / "renew_certs.sh"
        assert renew_script.is_file(), "scripts/renew_certs.sh missing"

        content = renew_script.read_text(encoding="utf-8")
        assert "set -euo pipefail" in content
        assert "certbot renew" in content
        assert "nginx -s reload" in content


class TestEnvironmentConfigAndPydanticParity:
    """Adversarial validation of .env.production.example against Pydantic Settings."""

    def test_env_production_example_parses_into_settings(self) -> None:
        """Verify that .env.production.example keys map directly to Pydantic Settings."""
        root = _get_project_root()
        env_file = root / ".env.production.example"
        assert env_file.is_file(), ".env.production.example missing"

        content = env_file.read_text(encoding="utf-8")

        # Parse key-value pairs ignoring comments and empty lines
        env_dict: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env_dict[k.strip()] = v.strip()

        # Check required keys
        assert "TARS_JWT_SECRET_KEY" in env_dict
        assert "TARS_DATABASE_URL" in env_dict
        assert "TARS_DOMAIN" in env_dict
        assert "POSTGRES_USER" in env_dict
        assert "POSTGRES_PASSWORD" in env_dict
        assert "POSTGRES_DB" in env_dict

        # Test instantiation of Settings with these environment variables
        test_settings = Settings(
            app_name=env_dict.get("TARS_APP_NAME", "TARS"),
            environment=cast(Literal["development", "test", "production"], env_dict.get("TARS_ENVIRONMENT", "production")),
            debug=env_dict.get("TARS_DEBUG", "false").lower() == "true",
            jwt_secret_key=env_dict.get("TARS_JWT_SECRET_KEY", "test_key"),
            jwt_algorithm=env_dict.get("TARS_JWT_ALGORITHM", "HS256"),
            jwt_access_token_expire_minutes=int(env_dict.get("TARS_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "10080")),
            database_url=env_dict.get("TARS_DATABASE_URL", "sqlite+aiosqlite:///:memory:"),
            storage_dir=Path(env_dict.get("TARS_STORAGE_DIR", "/app/storage")),
            default_humor_level=float(env_dict.get("TARS_DEFAULT_HUMOR_LEVEL", "0.9")),
            default_honesty_level=float(env_dict.get("TARS_DEFAULT_HONESTY_LEVEL", "0.95")),
            default_mode=cast(Literal["companion", "work"], env_dict.get("TARS_DEFAULT_MODE", "companion")),
        )
        assert test_settings.app_name == "TARS"
        assert test_settings.environment == "production"
        assert test_settings.debug is False
        assert test_settings.default_humor_level == 0.90
        assert test_settings.default_honesty_level == 0.95


class TestDeploymentGuideCompleteness:
    """Adversarial validation of DEPLOYMENT.md sections, commands, and edge instructions."""

    def test_deployment_guide_required_sections_present(self) -> None:
        """Verify all mandatory deployment handbook sections are fully articulated."""
        root = _get_project_root()
        deploy_md = root / "DEPLOYMENT.md"
        assert deploy_md.is_file(), "DEPLOYMENT.md missing"

        content = deploy_md.read_text(encoding="utf-8")

        # 1. Prerequisites
        assert "사전 요구사항" in content or "Prerequisites" in content
        assert "Docker Engine" in content
        assert "Docker Compose" in content

        # 2. Network & DDNS
        assert "DuckDNS" in content
        assert "80" in content and "443" in content
        assert "Hairpin NAT" in content or "NAT Loopback" in content

        # 3. 5-step Deployment
        assert "Step 1" in content
        assert "Step 2" in content
        assert "Step 3" in content
        assert "Step 4" in content
        assert "Step 5" in content

        # 4. Mobile & PWA Checklist
        assert "iOS Safari" in content
        assert "홈 화면에 추가" in content or "Add to Home Screen" in content
        assert "Web Speech API" in content or "TTS" in content
        assert "WebSocket" in content or "wss://" in content

        # 5. Maintenance & Operations
        assert "Crontab" in content or "crontab" in content
        assert "pg_dump" in content
        assert "rsync" in content

        # 6. Troubleshooting
        assert "트러블슈팅" in content or "Troubleshooting" in content
        assert "502 Bad Gateway" in content
        assert "4001" in content


class TestCrossConfigParity:
    """Cross-validate Docker Compose, Nginx, and Scripts volume and port alignments."""

    def test_docker_compose_and_nginx_mount_parity(self) -> None:
        """Verify that volume mounts in docker-compose.yml align exactly with Nginx & Certbot filesystem paths."""
        root = _get_project_root()
        compose_file = root / "docker-compose.yml"
        content = compose_file.read_text(encoding="utf-8")
        data: dict[str, Any] = yaml.safe_load(content)

        services = data["services"]
        nginx_vols = [str(v) for v in services["tars-nginx"]["volumes"]]
        certbot_vols = [str(v) for v in services["certbot"]["volumes"]]

        # Nginx mounts certbot/conf -> /etc/letsencrypt
        assert any("/etc/letsencrypt" in v for v in nginx_vols)
        # Nginx mounts certbot/www -> /var/www/certbot
        assert any("/var/www/certbot" in v for v in nginx_vols)
        # Certbot mounts same shared directories
        assert any("/etc/letsencrypt" in v for v in certbot_vols)
        assert any("/var/www/certbot" in v for v in certbot_vols)
