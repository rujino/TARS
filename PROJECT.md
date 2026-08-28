# Project: TARS Phase 4 - Production Infrastructure & Containerization Suite

## Architecture
TARS Phase 4 establishes an enterprise-grade, highly reliable, and containerized deployment stack for the TARS AI Companion backend. The architecture consists of four orchestrated service tiers connected through an isolated Docker bridge network (`tars-network`) with front-facing SSL/TLS termination and low-latency reverse proxying:

```
                  [ Public Internet / Mobile PWA Client ]
                                    │
                                    ▼ (Port 80 HTTP / 443 HTTPS & WSS)
                 ┌──────────────────────────────────────┐
                 │       tars-nginx (Nginx 1.25)        │
                 │  - SSL Termination (Let's Encrypt)   │
                 │  - HTTP -> HTTPS Redirect            │
                 │  - WebSocket ($connection_upgrade)   │
                 │  - SSE Zero-Buffering Proxy          │
                 │  - Security Headers & Gzip           │
                 │  - ACME Challenge Routing            │
                 └──────────────┬───────────────────────┘
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
┌───────────────────────────────────┐    ┌───────────────────────────────────┐
│     tars-backend (FastAPI)        │    │    certbot (Let's Encrypt)        │
│  - Python 3.11-slim + uv          │    │  - 12h Renewal Loop Daemon        │
│  - Non-Root `tarsuser` (10001)    │    │  - Shared Webroot & Certs Volumes │
│  - Alembic Auto-Migrations on Boot│    └───────────────────────────────────┘
│  - LangGraph + AI Companion Core  │
└─────────────────┬─────────────────┘
                  │ (Port 5432 asyncpg)
                  ▼
┌───────────────────────────────────┐
│    tars-db (PostgreSQL 16)        │
│  - Named Volume: postgres_data    │
│  - Healthcheck: pg_isready        │
│  - ACID & Relational Integrity    │
└───────────────────────────────────┘
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | `asyncpg` & `alembic` Dependencies | Add `asyncpg>=0.29.0` and `alembic>=1.13.1` to `pyproject.toml` via `uv` | M1 | Survey R2 |
| F2 | Alembic Environment & Base Discovery | Configure `alembic.ini` and `migrations/env.py` with async engine and `tars.db.base.Base` metadata | M1 | Survey R2 |
| F3 | Initial Baseline Migration | Generate `migrations/versions/0001_initial_schema.py` covering all 5 ORM tables (users, tars_settings, user_wikis, chat_sessions, chat_messages) with SQLite & PostgreSQL compatibility | M1 | Survey R2 |
| F4 | Container Migration Bootstrapper | Create `scripts/run_migrations.sh` with DB connectivity polling and `alembic upgrade head` execution | M1 | Survey R2 |
| F5 | Migration Regression Tests | Implement `tests/tier1_unit/test_alembic_migrations.py` verifying upgrade/downgrade and zero schema drift (`alembic check`) | M1 | Survey R2 |
| F6 | Multi-Stage Dockerfile | Create `Dockerfile` with builder (`uv` cache mounts) and runtime (`python:3.11-slim`, non-root `tarsuser`, healthcheck) | M2 | Survey R1 |
| F7 | Production Docker Compose | Create `docker-compose.yml` orchestrating `tars-backend`, `tars-db`, `tars-nginx`, `certbot` with healthchecks, volumes, and networks | M2 | Survey R1 |
| F8 | Local Development Compose Override | Create `docker-compose.override.yml` for local live reload, source mounts, and port exposures | M2 | Survey R1 |
| F9 | Container Entrypoint Script | Create `scripts/entrypoint.sh` executing migrations and launching Uvicorn cleanly | M2 | Survey R1 |
| F10 | Nginx Main Configuration | Create `nginx/nginx.conf` with Gzip compression, worker tuning, 50MB upload limits, and `$connection_upgrade` map | M3 | Survey R3 |
| F11 | Nginx Virtual Host & Proxy Rules | Create `nginx/conf.d/default.conf` with SSL modern ciphers, ACME challenge, WebSocket upgrade (`/api/v1/chat/ws`), and SSE zero-buffering (`/api/v1/chat/stream`) | M3 | Survey R3 |
| F12 | SSL Bootstrap & Renewal Scripts | Create `scripts/init_ssl.sh` supporting self-signed dev mode and Let's Encrypt certbot issuance, plus `scripts/renew_certs.sh` | M3 | Survey R3 |
| F13 | Production Environment Template | Create `.env.production.example` detailing all 7 configuration sections (Core, Security, Postgres, Domain/SSL, LLM, Storage, Integrations) | M4 | Survey R4 |
| F14 | Comprehensive Deployment Guide | Create `DEPLOYMENT.md` covering prerequisites, DuckDNS/Cloudflare DDNS, router port forwarding (80/443), hairpin NAT, step-by-step deploy, iOS PWA / Web Speech TTS / WSS verification, and troubleshooting | M4 | Survey R4 |
| F15 | E2E Infrastructure Validation | Verify complete test suite (Tiers 1-4), static analysis (`mypy --strict`, `ruff check`), and container configuration validity | M5 | Acceptance Criteria |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Production Database & Alembic Migrations | F1, F2, F3, F4, F5 | none | DONE |
| M2 | Multi-stage Dockerfile & Compose Stack | F6, F7, F8, F9 | M1 | DONE |
| M3 | Nginx Reverse Proxy & SSL Automation | F10, F11, F12 | M2 | IN_PROGRESS |
| M4 | Host Environment & Deployment Guide | F13, F14 | M3 | PLANNED |
| M5 | Final Milestone: 100% E2E Pass & Adversarial Hardening | F15, Tier 1-5 validation | M1, M2, M3, M4 | PLANNED |

---

## Interface Contracts

### 1. Database & Alembic Integration Contract
- `alembic.ini` points to `script_location = migrations`.
- `migrations/env.py` dynamically injects `database_url` from `tars.config.get_settings().database_url`.
- `target_metadata = Base.metadata` discoverable across all models (`users`, `tars_settings`, `user_wikis`, `chat_sessions`, `chat_messages`).
- Migration `0001_initial_schema.py` must support `render_as_batch=True` for SQLite compatibility and standard DDL for PostgreSQL (`postgresql+asyncpg://...`).

### 2. Docker & Backend Runtime Contract
- Base image: `python:3.11-slim`.
- Package manager: `uv` (binary imported via `ghcr.io/astral-sh/uv:0.6`).
- System user: `tarsuser` (UID: 10001, GID: 10001).
- Healthcheck endpoint: `http://localhost:8000/health` returning HTTP 200 `{"status": "ok", "app": "TARS"}`.
- Storage volumes: `/app/storage` (OKF files) and `/app/data` (runtime data).

### 3. Nginx Reverse Proxy & Streaming Contract
- Upstream: `http://tars-backend:8000`.
- WebSocket `/api/v1/chat/ws`:
  - `proxy_http_version 1.1;`
  - `proxy_set_header Upgrade $http_upgrade;`
  - `proxy_set_header Connection $connection_upgrade;`
  - `proxy_read_timeout 3600s;`
  - `proxy_buffering off;`
- Server-Sent Events `/api/v1/chat/stream`:
  - `proxy_http_version 1.1;`
  - `proxy_set_header Connection "";`
  - `proxy_set_header X-Accel-Buffering no;`
  - `chunked_transfer_encoding on;`
  - `proxy_buffering off;`
  - `proxy_cache off;`
  - `proxy_read_timeout 300s;`
- ACME Challenge: `/.well-known/acme-challenge/` mapped to `/var/www/certbot`.

---

## Code Layout
```
TARS/
├── Dockerfile                         # Multi-stage production container build
├── docker-compose.yml                 # Production multi-service orchestration
├── docker-compose.override.yml        # Local development override
├── pyproject.toml                     # Dependencies (asyncpg, alembic added via uv)
├── alembic.ini                        # Alembic configuration
├── migrations/
│   ├── env.py                         # Async Alembic runner & Base metadata discovery
│   ├── script.py.mako                 # Migration template
│   └── versions/
│       └── 0001_initial_schema.py     # Initial schema DDL migration
├── nginx/
│   ├── nginx.conf                     # Nginx core configuration (Gzip, Events, Map)
│   └── conf.d/
│       └── default.conf               # Virtual host, SSL, WS/SSE reverse proxy
├── scripts/
│   ├── entrypoint.sh                  # Container entrypoint & migration runner
│   ├── run_migrations.sh              # Standalone migration wrapper with DB polling
│   ├── init_ssl.sh                    # SSL bootstrap (self-signed dev & Let's Encrypt)
│   └── renew_certs.sh                 # Certbot renewal helper
├── .env.production.example            # Production environment variables template
├── DEPLOYMENT.md                      # Production deployment & operations guide
├── tests/
│   ├── conftest.py                    # Pytest configuration & async DB fixtures
│   ├── tier1_unit/
│   │   ├── test_alembic_migrations.py # Migration upgrade/downgrade & drift tests
│   │   └── test_adversarial_phase4_m1.py # Adversarial stress tests
│   ├── tier2_integration/
│   │   └── test_infra_config.py       # Docker, Compose & Nginx configuration tests
│   └── ...                            # Existing Tier 1-4 tests
└── tars/                              # Application source code
```
