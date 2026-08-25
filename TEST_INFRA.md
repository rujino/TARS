# TARS Test Infrastructure & Quality Assurance Specification (`TEST_INFRA.md`)

## 1. Overview & Testing Philosophy

The TARS testing framework is engineered to guarantee **zero data loss, multi-tenant isolation, strict type safety, and real-time streaming reliability** across the entire Phase 1 Core MVP stack.

The test infrastructure is structured into **4 distinct tiers**, progressing from isolated unit logic to end-to-end multi-tenant workflows.

```
+------------------------------------------------------------------------------------+
| Tier 4: Application Workflows (Multi-Tenant Isolation, Full Conversation Loops)   |
+------------------------------------------------------------------------------------+
                                          |
+------------------------------------------------------------------------------------+
| Tier 3: E2E API & Streaming Tests (FastAPI REST, WebSocket, SSE Token Streams)     |
+------------------------------------------------------------------------------------+
                                          |
+------------------------------------------------------------------------------------+
| Tier 2: Integration Tests (Hybrid LLM Adapters, LangGraph StateGraph, Extractor)  |
+------------------------------------------------------------------------------------+
                                          |
+------------------------------------------------------------------------------------+
| Tier 1: Core Unit Tests (OKF Engine, Storage Manager, DB Reconciler, Slicer, etc.) |
+------------------------------------------------------------------------------------+
```

---

## 2. Test Tiers & Scope Breakdown

| Tier | Directory | Target Features | Scope & Focus |
|:---|:---|:---|:---|
| **Tier 1: Unit** | `tests/tier1_unit/` | F1, F2, F3, F4, F5, F6, F7 | - OKF YAML Frontmatter parsing, validation, and canonical serialization<br>- Multi-tenant storage path sandbox & atomic write protection<br>- SQLAlchemy 2.0 Async model constraints and Storage-DB reconciliation<br>- Multi-factor dynamic slicing score formula and token packing<br>- TARS Persona system prompt generation & parameter matrices |
| **Tier 2: Integration** | `tests/tier2_integration/` | F8, F9, F10, F11, F12, F13 | - BaseLLMAdapter implementations (`GeminiAdapter`, `LlamaCppAdapter`)<br>- Intent routing, 500ms SLM health probe, circuit breaker fallback<br>- LangGraph `StateGraph` node transitions & memory reducer<br>- Background `SelfEvolvingKnowledgeWorker` extraction and sync |
| **Tier 3: E2E API** | `tests/tier3_e2e_api/` | F14, F15, F16, F17, F18 | - JWT user authentication, password hashing (bcrypt), DI security<br>- TARS Persona settings API (`GET`, `PATCH`, `POST /reset`)<br>- WebSocket bidirectional streaming (`/api/v1/chat/ws`) with ping/pong & lifecycle<br>- SSE real-time token stream endpoint (`POST /api/v1/chat/stream`) |
| **Tier 4: Application** | `tests/tier4_application/` | F19, F20 | - Multi-turn conversational self-evolving knowledge extraction loops<br>- Cross-tenant file & database isolation verification<br>- Adversarial fuzzing, path traversal penetration, and malformed payload resilience |

---

## 3. Fixture Architecture (`tests/conftest.py`)

All tests share a centralized, async-native fixture catalog located in `tests/conftest.py`:

```
tests/conftest.py
├── Database Fixtures
│   ├── async_db_engine       # In-memory SQLite async engine (aiosqlite)
│   └── async_db_session      # Isolated AsyncSession per test with rollback/cleanup
├── Storage Fixtures
│   ├── temp_storage_dir      # Isolated temporary directory (pytest tmp_path)
│   └── test_storage_manager  # Pre-configured FileStorageManager instance
├── Mock LLM Adapters
│   ├── mock_gemini_adapter   # Mock adapter simulating Gemini 2.0 streaming & tool calls
│   └── mock_llamacpp_adapter # Mock adapter simulating local SLM latency & health checks
├── Authentication & User
│   ├── test_user             # Pre-seeded User instance with default TARS settings
│   └── auth_headers          # Pre-generated JWT Bearer Authorization headers
└── Sample OKF Data Fixtures
    ├── sample_okf_text_valid # Standard YAML Frontmatter + Markdown content
    └── sample_okf_doc        # Valid parsed OKFDocument instance
```

---

## 4. Test Execution Guide

All test suites are executed via `pytest` within the project's `uv` virtual environment.

### 4.1. Run Full Test Suite
```bash
uv run pytest
```

### 4.2. Run by Test Tier
```bash
# Tier 1: Core Unit Tests
uv run pytest tests/tier1_unit -v

# Tier 2: Integration Tests
uv run pytest tests/tier2_integration -v

# Tier 3: API & Streaming Tests
uv run pytest tests/tier3_e2e_api -v

# Tier 4: Application & Multi-Tenant Tests
uv run pytest tests/tier4_application -v
```

### 4.3. Run Specific Feature Unit Tests
```bash
# OKF Parser & Validator (F1, F2)
uv run pytest tests/tier1_unit/test_okf_engine.py -v

# Storage Manager & Path Traversal Sandbox (F3)
uv run pytest tests/tier1_unit/test_storage_manager.py -v

# DB Models & Reconciliation Sync (F4, F5)
uv run pytest tests/tier1_unit/test_db_reconciliation.py -v

# OKF Dynamic Slicer (F6)
uv run pytest tests/tier1_unit/test_dynamic_slicer.py -v

# TARS Persona System Prompt Engine (F7)
uv run pytest tests/tier1_unit/test_persona_prompt.py -v
```

### 4.4. Coverage & Quality Gates
```bash
# Generate terminal and HTML coverage report
uv run pytest --cov=tars --cov-report=term-missing --cov-report=html

# Strict static type check
uv run mypy tars tests --strict
```

---

## 5. Quality Standards & Adversarial Verification

1. **Independence & Isolation**: Every test creates its own in-memory database session and temporary directory to guarantee zero test order dependency.
2. **Deterministic Output Matching**: Output assertions derive strictly from `docs/OKF_SPEC.md`, `docs/ARCHITECTURE.md`, and `docs/PRD.md`.
3. **Adversarial Verification**:
   - **Path Traversal Security**: Explicitly asserts rejection of `../`, absolute paths, and null bytes (`\0`).
   - **Malformed YAML/Markdown**: Frontmatter missing delimiters or invalid types must raise explicit custom exceptions (`OKFInvalidFrontmatterError`, `OKFValidationError`).
   - **Embedded Delimiters**: Markdown bodies containing internal `---` horizontal rules must not break frontmatter parsing.
