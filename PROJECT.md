# Project: TARS Background Task Lifecycle Refactoring & Production Readiness Audit

## Architecture
- Presentation Layer: `tars/api/routers/chat.py` — handles WebSocket and HTTP routes, stream serialization, client events. Decoupled from background tasks; does not cancel or clear background tasks on client disconnect.
- Business Layer: `tars/services/agent_chat.py` — executes business logic, invokes agent workflow, schedules background knowledge extraction. Re-raises `asyncio.CancelledError` and logs unexpected exceptions with `logger.error(..., exc_info=True)`.
- Orchestration Layer: `tars/orchestrator/nodes.py` — manages node tasks set `_background_node_tasks` and exports `shutdown_background_tasks(timeout: float = 5.0)` for graceful draining during application shutdown.
- Application Lifespan: `tars/api/app.py` — FastAPI lifespan context manager. Drains pending tasks cleanly via `await shutdown_background_tasks(timeout=5.0)`.
- Test Suite: `tests/tier3_e2e_api/test_websocket_streaming.py` — E2E WebSocket test suite validating disconnection resilience, multi-user isolation, and lifespan shutdown.
- Documentation / Production Audit: `docs/PRODUCTION_READINESS_AUDIT.md` — comprehensive audit report across concurrency, resources, resilience, and telemetry.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| 1 | Presentation decoupling | Remove `_background_ws_tasks` import and forced cancel/clear in `chat.py` finally block | M1 | Spec §3.1 |
| 2 | Business error logging | Remove `_background_ws_tasks` re-export, handle `asyncio.CancelledError`, log `logger.error(..., exc_info=True)` in `agent_chat.py` | M1 | Spec §3.2 |
| 3 | Orchestration shutdown helper | Implement and export `shutdown_background_tasks(timeout: float = 5.0)` in `nodes.py` | M1 | Spec §3.3 |
| 4 | Lifespan graceful shutdown | Integrate `await shutdown_background_tasks(timeout=5.0)` into `app.py:lifespan` | M1 | Spec §3.4 |
| 5 | WebSocket disconnect resilience test | Verify client disconnect does not cancel background extraction task | M2 | Spec §4.1 / R2 |
| 6 | Multi-user isolation test | Verify User A disconnecting does not cancel User B's active background tasks | M2 | Spec §4.1 / R2 |
| 7 | Lifespan shutdown test | Verify `shutdown_background_tasks` awaits running tasks and handles timeouts cleanly | M2 | Spec §4.1 / R2 |
| 8 | Tier 3 test suite regression run | Ensure 100% pass rate across all tests in `tests/tier3_e2e_api/` | M2 | R2 |
| 9 | Production readiness audit report | Author `docs/PRODUCTION_READINESS_AUDIT.md` with 4-category analysis, severity, root cause, remediation | M3 | R3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| M1 | Background Task Concurrency Isolation & Graceful Shutdown | `tars/api/routers/chat.py`, `tars/services/agent_chat.py`, `tars/orchestrator/nodes.py`, `tars/api/app.py` | Survey | DONE |
| M2 | Comprehensive Verification & Regression Prevention | `tests/tier3_e2e_api/test_websocket_streaming.py` + pytest tier3 run | M1 | DONE |
| M3 | Production Readiness Audit & Vulnerability Report | `docs/PRODUCTION_READINESS_AUDIT.md` | Survey | DONE |

## Interface Contracts
### `tars.orchestrator.nodes` -> `tars.api.app`
- Function: `async def shutdown_background_tasks(timeout: float = 5.0) -> None`
- Parameters: `timeout: float = 5.0`
- Semantics: waits for pending tasks in `_background_node_tasks` via `asyncio.wait(pending, timeout=timeout)`. Cancels only remaining tasks that exceed timeout, awaits their cleanup with `asyncio.gather(*still_pending, return_exceptions=True)`, and clears the set.
- Exported in: `__all__` in `tars/orchestrator/nodes.py`.

### `tars.services.agent_chat` -> `tars.api.routers.chat`
- `_background_ws_tasks` is completely removed from both modules.
- `execute_background_knowledge_extraction` retains its signature and behavior.
- `tars.api.routers.chat` retains compatibility alias `_execute_background_knowledge_extraction = execute_background_knowledge_extraction`.

## Code Layout
- Exclusive write ownership for M1 Worker:
  - `tars/api/routers/chat.py`
  - `tars/services/agent_chat.py`
  - `tars/orchestrator/nodes.py`
  - `tars/api/app.py`
- Exclusive write ownership for M2 Worker / Test Writer:
  - `tests/tier3_e2e_api/test_websocket_streaming.py`
- Exclusive write ownership for M3 Worker / Auditor:
  - `docs/PRODUCTION_READINESS_AUDIT.md`
