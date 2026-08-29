# E2E Test Infra: TARS Phase 4 - Production Infrastructure & Containerization Suite

## 1. Test Philosophy
- **Opaque-Box & Requirement-Driven**: Tests validate interface contracts, configuration syntaxes, migration schemas, and end-to-end container orchestration behaviors against the authoritative requirements in `PROJECT.md` and `ORIGINAL_REQUEST.md`.
- **Deterministic & Isolated Execution**: All tests are runnable in the isolated `uv` virtual environment using `pytest` without requiring external network access or pre-existing cloud infrastructure.
- **Zero Schema Drift Policy**: Database migrations and SQLAlchemy ORM metadata (`tars.db.base.Base.metadata`) must remain in 100% synchronization, verified through automated bidirectional migration runs and schema drift assertions.
- **Defensive Infrastructure Validation**: Container definitions (`Dockerfile`, `docker-compose.yml`), reverse proxy rules (`nginx.conf`, `default.conf`), SSL bootstrapper scripts (`scripts/init_ssl.sh`), and environment configurations (`.env.production.example`) are rigorously validated via AST, regex, and structured schema parsers for security, resilience, and low-latency streaming compliance.

---

## 2. Feature Inventory & Test Mapping
| # | Feature ID | Feature Name | Requirement | Tier 1 Unit | Tier 2 Integration | Tier 3 E2E API | Tier 4 Scenario | Status |
|---|------------|--------------|-------------|:-----------:|:------------------:|:--------------:|:---------------:|:------:|
| 1 | F1 | `asyncpg` & `alembic` Dependencies | R2 | ✓ | ✓ | - | - | Verified |
| 2 | F2 | Alembic Async Engine & Metadata Discovery | R2 | ✓ | ✓ | - | - | Verified |
| 3 | F3 | Baseline Migration Schema (`0001_initial_schema`) | R2 | ✓ | ✓ | - | ✓ | Verified |
| 4 | F4 | Database Migration Bootstrapper (`run_migrations.sh`) | R2 | ✓ | ✓ | - | ✓ | Verified |
| 5 | F5 | Migration Regression & Schema Drift (`alembic check`) | R2 | ✓ | - | - | - | Verified |
| 6 | F6 | Multi-Stage Dockerfile (`python:3.11-slim` + `uv`) | R1 | - | ✓ | - | ✓ | Verified |
| 7 | F7 | Production Docker Compose (`tars-backend`, `tars-db`, `tars-nginx`, `certbot`) | R1 | - | ✓ | - | ✓ | Verified |
| 8 | F8 | Local Development Compose Override | R1 | - | ✓ | - | - | Verified |
| 9 | F9 | Container Entrypoint Script (`entrypoint.sh`) | R1 | - | ✓ | - | ✓ | Verified |
| 10 | F10 | Nginx Main Configuration (`nginx.conf`) | R3 | - | ✓ | - | - | Verified |
| 11 | F11 | Nginx Virtual Host & Streaming Proxy (`default.conf`) | R3 | - | ✓ | ✓ | ✓ | Verified |
| 12 | F12 | SSL Bootstrap & Renewal Scripts (`init_ssl.sh`, `renew_certs.sh`) | R3 | - | ✓ | - | ✓ | Verified |
| 13 | F13 | Production Environment Template (`.env.production.example`) | R4 | - | ✓ | - | - | Verified |
| 14 | F14 | Comprehensive Deployment Guide (`DEPLOYMENT.md`) | R4 | - | ✓ | - | - | Verified |
| 15 | F15 | Complete E2E Suite & Strict Type/Lint Integrity | AC | ✓ | ✓ | ✓ | ✓ | Verified |

---

## 3. Test Architecture & Directory Layout
```
tests/
├── conftest.py                             # Shared pytest fixtures (async DB engine, mock adapters, auth)
├── tier1_unit/
│   ├── test_alembic_migrations.py          # [Phase 4] Migration upgrade/downgrade, drift, SQLite batch
│   ├── test_smart_session.py               # [Phase 3] Session lifecycle & decay models
│   ├── test_tool_registry_and_cag.py       # [Phase 3] Static CAG & tool registry
│   ├── test_mcp_client_adapter.py          # [Phase 3] MCP Client JSON-RPC protocol
│   ├── test_google_workspace_adapters.py   # [Phase 3] Calendar & Gmail adapters
│   ├── test_dynamic_slicer.py              # [Phase 3] 5-factor dynamic slicing
│   ├── test_okf_engine.py                  # [Phase 1] OKF Markdown engine
│   ├── test_storage_manager.py             # [Phase 1] Multi-tenant storage manager
│   └── test_adversarial_*.py               # Adversarial and stress unit suites
├── tier2_integration/
│   ├── test_infra_config.py                # [Phase 4] Dockerfile, Compose, Nginx, Env, Scripts
│   ├── test_langgraph_pipeline.py          # [Phase 3] LangGraph multi-turn loop & ReAct
│   ├── test_knowledge_extractor.py         # [Phase 3] Background self-evolution loop
│   ├── test_db_reconciliation.py           # [Phase 1] DB & storage synchronization
│   └── test_adversarial_*.py               # Adversarial fallback & stress integration suites
├── tier3_e2e_api/
│   ├── test_chat_streaming_api.py          # [Phase 2] WebSocket & SSE streaming endpoints
│   ├── test_auth_api.py                    # [Phase 1/2] JWT signup/login/token validation
│   ├── test_persona_api.py                 # [Phase 2] TARS settings slider & config API
│   ├── test_greeting_api.py                # [Phase 3] Proactive greeting endpoint
│   └── test_static_pwa_api.py              # [Phase 2] PWA static files, manifest, sw.js
└── tier4_application/
    ├── test_full_conversation_loop.py      # Multi-turn conversation & knowledge self-evolution
    └── test_deployment_readiness.py        # Infrastructure readiness & startup flow verification
```

---

## 4. Real-World End-to-End Scenarios
1. **Database Schema Lifecycle & Rollback Scenario**:
   - Starting from an uninitialized database, `alembic upgrade head` provisions all 5 core entity tables (`users`, `tars_settings`, `user_wikis`, `chat_sessions`, `chat_messages`) and the `alembic_version` metadata table.
   - Reverting with `alembic downgrade base` cleanly removes all application tables without orphan foreign key constraint violations.
   - Autogenerate drift check (`alembic check`) asserts zero discrepancies between ORM models and migration revisions.
2. **Container Multi-Stage Build & Security Isolation Scenario**:
   - The multi-stage `Dockerfile` uses `python:3.11-slim` with `uv` cache mounting for sub-second deterministic builds.
   - The runtime container operates strictly under non-root system user `tarsuser` (UID: 10001, GID: 10001) with persistent data directories (`/app/storage`, `/app/data`).
   - Container healthcheck (`curl -f http://localhost:8000/health`) responds within 5 seconds of container boot.
3. **Zero-Buffering Reverse Proxy Streaming Scenario**:
   - `nginx/conf.d/default.conf` configures `proxy_buffering off`, `proxy_cache off`, and `chunked_transfer_encoding on` for `/api/v1/chat/stream` (SSE), preventing token batching.
   - WebSocket proxying (`/api/v1/chat/ws`) maps `$connection_upgrade` and sets `proxy_read_timeout 3600s`, ensuring long-lived persistent connections.
4. **SSL Bootstrap & Certificate Renewal Scenario**:
   - `scripts/init_ssl.sh` generates self-signed SAN certificates for local development and provisions Let's Encrypt certificates in production via Certbot webroot ACME challenge.

---

## 5. Coverage Thresholds & Quality Gates
| Tier | Description | Minimum Coverage Target | Enforcement Tool |
|------|-------------|:-----------------------:|:----------------:|
| **Tier 1** | Unit & Migration Tests | >= 5 assertions per feature | `pytest tests/tier1_unit/` |
| **Tier 2** | Infrastructure & Integration Tests | 100% config directives validated | `pytest tests/tier2_integration/` |
| **Tier 3** | E2E API & Protocol Tests | 100% route & status code coverage | `pytest tests/tier3_e2e_api/` |
| **Tier 4** | Real-World Application Scenarios | Complete multi-service lifecycle | `pytest tests/tier4_application/` |
| **Static Analysis** | Strict Typing & Zero Lint Warnings | 100% Pass (0 errors) | `mypy --strict`, `ruff check` |

---

## 6. Test Execution Commands
- **Full Test Suite Execution**:
  ```bash
  uv run pytest tests/ -v
  ```
- **Phase 4 Infrastructure Tests Only**:
  ```bash
  uv run pytest tests/tier1_unit/test_alembic_migrations.py tests/tier2_integration/test_infra_config.py -v
  ```
- **Strict Static Type Checking**:
  ```bash
  uv run mypy --strict tars tests
  ```
- **Linter & Code Formatting Check**:
  ```bash
  uv run ruff check tars tests
  ```
