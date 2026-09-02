# Project: TARS Phase 4 - Production K3s Infrastructure & SLM Serving Suite

## Architecture
TARS Phase 4 establishes an enterprise-grade, highly reliable, and containerized deployment stack for the TARS AI Companion backend on **K3s (Lightweight Kubernetes)**. The architecture consists of orchestrated Kubernetes workloads connected through standard cluster DNS networking and persistent volume claims (`local-path`), front-faced with Traefik Ingress and cert-manager automated Let's Encrypt SSL/TLS termination:

```
                  [ Public Internet / Mobile Edge Client ]
                                     │
                                     ▼ (Port 80 HTTP / 443 HTTPS & WSS)
                 ┌──────────────────────────────────────┐
                 │       Traefik Ingress Controller     │
                 │  - Ingress: k8s/05-ingress.yaml      │
                 │  - SSL Termination (Let's Encrypt)   │
                 │  - cert-manager ClusterIssuer        │
                 │  - WebSocket & SSE Low-Latency Route │
                 └──────────────────┬───────────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
┌──────────────────────────────────────┐          ┌──────────────────────────────────────┐
│  tars-backend (FastAPI 3 Replicas)   │          │        tars-db (PostgreSQL 16)       │
│  - Python 3.11-slim + uv             │          │  - Deployment + Service (Port 5432)  │
│  - Non-Root `tarsuser` (10001)       │          │  - PersistentVolumeClaim (10Gi)      │
│  - Alembic Auto-Migrations on Boot   │◄─────────┤  - Secret/ConfigMap Credentials      │
│  - Liveness & Readiness Probes       │          │  - ACID & Relational Integrity       │
│  - tars-storage-pvc (10Gi OKF)       │          └──────────────────────────────────────┘
│  - tars-data-pvc (5Gi Runtime)       │
└──────────────────┬───────────────────┘
                   │ (Internal HTTP / OpenAI API)
                   ▼
┌──────────────────────────────────────┐
│  Local SLM (llama-server / llama.cpp)│
│  - Port 8080 (GGUF C++ Low-Memory)   │
│  - Fast Intent Classification        │
│  - Query Preprocessing & Filtering   │
│  - Automated Fallback to Gemini      │
└──────────────────────────────────────┘
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
| F7 | K3s Core Manifests | Create `k8s/00-namespace.yaml`, `k8s/01-config.yaml`, and `k8s/01-secret.example.yaml` for namespace, config, and secret isolation | M2 | Survey R1 |
| F8 | K3s Database & PVC Manifest | Create `k8s/02-db.yaml` with PostgreSQL 16 Deployment, ClusterIP Service, and 10Gi `local-path` PersistentVolumeClaim | M2 | Survey R1 |
| F9 | K3s Backend 3-Replica Manifest | Create `k8s/03-backend.yaml` with 3-replica Deployment, Liveness/Readiness probes, 10Gi/5Gi PVCs, and ClusterIP Service | M2 | Survey R1 |
| F10 | K3s Ingress & cert-manager | Create `k8s/04-cluster-issuer.example.yaml` and `k8s/05-ingress.example.yaml` with Traefik and Let's Encrypt TLS termination | M3 | Survey R3 |
| F11 | One-Click Deployment Automation | Create `k8s/deploy.sh` executing Docker build, K3s containerd image import, manifest application, and rolling restarts | M3 | Survey R3 |
| F12 | Local SLM (llama-server) Integration | Provide `llama-server` configuration guide, `TARS_LLAMACPP_BASE_URL` routing, and `scripts/test_slm.py` diagnostic suite | M4 | Survey R4 |
| F13 | Production Deployment Guide | Create `DEPLOYMENT.md` detailing hardware prereqs, DDNS, router port forwarding (80/443), K3s installation, SLM setup, and troubleshooting | M4 | Survey R4 |
| F14 | Comprehensive Documentation Parity | Update all architectural, stack, and PRD specifications (`PRD.md`, `ARCHITECTURE.md`, `TECH_STACK.md`, `README.md`) | M4 | Survey R4 |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Production Database & Alembic Migrations | F1, F2, F3, F4, F5 | none | DONE |
| M2 | Multi-stage Dockerfile & K3s Core Workloads | F6, F7, F8, F9 | M1 | DONE |
| M3 | Traefik Ingress, cert-manager & deploy.sh | F10, F11 | M2 | DONE |
| M4 | SLM Serving, Deployment Guide & Docs | F12, F13, F14 | M3 | DONE |

---

## Interface Contracts

### 1. Database & Alembic Integration Contract
- `alembic.ini` points to `script_location = migrations`.
- `migrations/env.py` dynamically injects `database_url` from `tars.config.get_settings().database_url`.
- `target_metadata = Base.metadata` discoverable across all models (`users`, `tars_settings`, `user_wikis`, `chat_sessions`, `chat_messages`).
- Migration `0001_initial_schema.py` supports standard DDL for PostgreSQL (`postgresql+asyncpg://...`) and `render_as_batch=True` for SQLite.

### 2. Docker & Backend Runtime Contract
- Base image: `python:3.11-slim`.
- Package manager: `uv` (binary imported via `ghcr.io/astral-sh/uv:0.6`).
- System user: `tarsuser` (UID: 10001, GID: 10001).
- Healthcheck / Probes endpoint: `http://localhost:8000/health` returning HTTP 200 `{"status": "ok", "app": "TARS"}`.
- Storage volumes: `/app/storage` (OKF files, PVC 10Gi) and `/app/data` (runtime data, PVC 5Gi).

### 3. K3s Ingress & Traefik Reverse Proxy Contract
- Backend Service: `http://tars-backend:8000` in namespace `tars`.
- Ingress: `k8s/05-ingress.yaml` with `traefik` ingressClassName and cert-manager annotation `cert-manager.io/cluster-issuer: letsencrypt-prod`.
- Real-time Streaming: Traefik automatically preserves WebSocket (`/api/v1/chat/ws`) and Server-Sent Events (`/api/v1/chat/stream`) unbuffered connections.

### 4. Local SLM (llama-server) Contract
- Endpoint: OpenAI-compatible `/v1/chat/completions` and `/health`.
- Format: GGUF model quantization (e.g. Q4_K_M).
- Configuration: `TARS_LLAMACPP_BASE_URL` in `k8s/01-config.yaml`.
- Resilience: Non-blocking Circuit Breaker fallback to Google Gemini on error or timeout.

---

## Code Layout
```
TARS/
├── Dockerfile                         # Multi-stage production container build
├── pyproject.toml                     # Dependencies (asyncpg, alembic added via uv)
├── alembic.ini                        # Alembic configuration
├── k8s/                               # K3s production Kubernetes manifests
│   ├── 00-namespace.yaml              # Namespace 'tars'
│   ├── 01-config.yaml                 # ConfigMap (Domain, Env, DB, SLM)
│   ├── 01-secret.example.yaml         # Secret template (JWT, DB password, Gemini Key)
│   ├── 02-db.yaml                     # PostgreSQL 16 Deployment, PVC 10Gi, Service
│   ├── 03-backend.yaml                # FastAPI 3-Replica Deployment, PVCs, Probes, Service
│   ├── 04-cluster-issuer.example.yaml # cert-manager Let's Encrypt ClusterIssuer template
│   ├── 05-ingress.example.yaml        # Traefik Ingress with TLS & domain routing template
│   ├── deploy.sh                      # Automated build, containerd import & deploy script
│   └── readme.md                      # K3s manifests quick guide
├── migrations/
│   ├── env.py                         # Async Alembic runner & Base metadata discovery
│   ├── script.py.mako                 # Migration template
│   └── versions/
│       └── 0001_initial_schema.py     # Initial schema DDL migration
├── scripts/
│   ├── entrypoint.sh                  # Container entrypoint & migration runner
│   ├── run_migrations.sh              # Standalone migration wrapper with DB polling
│   └── test_slm.py                    # Local SLM (llama-server) diagnostic & probe tool
├── .env.example                       # Development environment template
├── .env.production.example            # Production environment variables template
├── DEPLOYMENT.md                      # K3s production deployment & operations guide
├── docs/                              # Specification & Architecture documents
│   ├── PRD.md                         # Product Requirements Document
│   ├── ARCHITECTURE.md                # System Architecture & K3s layout
│   ├── TECH_STACK.md                  # Tech Stack Definitions & Rationale
│   ├── OKF_SPEC.md                    # Open Knowledge Format Specification
│   └── IDEAS.md                       # Vision & Feature Concepts
└── tars/                              # Application source code
```
