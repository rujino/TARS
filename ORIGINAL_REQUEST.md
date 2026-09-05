# Original User Request

## 2026-09-05T04:53:58Z

Use a full team of agents to refactor the TARS background task lifecycle and multi-user concurrency isolation in accordance with docs/BACKGROUND_TASK_REFACTORING_SPEC.md, while simultaneously conducting an in-depth production readiness audit across the codebase to identify potential architectural, concurrency, and reliability bottlenecks.

Working directory: /home/ryuji/Workspace/TARS
Integrity mode: development

## Reference Specification
- docs/BACKGROUND_TASK_REFACTORING_SPEC.md

## Requirements

### R1. Background Task Concurrency Isolation & Graceful Shutdown
Implement the exact architectural changes specified in docs/BACKGROUND_TASK_REFACTORING_SPEC.md:
- Presentation Layer (tars/api/routers/chat.py): Remove all imports and usages of _background_ws_tasks. Remove the forced cancel() and clear() logic in the finally block of chat_stream_ws.
- Business Layer (tars/services/agent_chat.py): Remove _background_ws_tasks re-export. Update execute_background_knowledge_extraction exception handling: re-raise asyncio.CancelledError with a warning, and log all other unexpected exceptions as errors with full stack trace (logger.error(..., exc_info=True)).
- Orchestration Layer (tars/orchestrator/nodes.py): Implement and export shutdown_background_tasks(timeout: float = 5.0). Safely await pending tasks using asyncio.wait(..., timeout=timeout) and cancel only those that exceed the timeout.
- Application Lifespan (tars/api/app.py): Integrate await shutdown_background_tasks(timeout=5.0) into the FastAPI lifespan handler to guarantee clean shutdown.

### R2. Comprehensive Verification & Regression Prevention
- In tests/tier3_e2e_api/test_websocket_streaming.py, implement new test cases covering:
  1. WebSocket disconnection resilience: Disconnecting a client does not cancel or interrupt background extraction tasks.
  2. Multi-user concurrency isolation: User A disconnecting does not affect or cancel User B's active background tasks.
  3. Lifespan graceful shutdown: shutdown_background_tasks properly awaits running tasks and handles timeouts cleanly.
- Ensure 100% test pass rate across all existing and new tests in tests/tier3_e2e_api/.

### R3. Production Readiness Audit & Vulnerability Report
- Conduct a comprehensive code audit evaluating the application against production-grade standards, focusing on:
  1. Concurrency & Async Hygiene (task leaks, unhandled exceptions in background loops, event loop blocking).
  2. Resource & Connection Management (database session handling, connection pooling, file descriptors, memory retention in long-lived state).
  3. Error Boundaries & Resilience (circuit breaking, fallback handling when external LLM/APIs fail or time out, client disconnect during generation).
  4. Observability & Telemetry (structured logging, tracing context propagation across async tasks).
- Produce a structured markdown report at docs/PRODUCTION_READINESS_AUDIT.md categorizing findings by severity (Critical / High / Medium / Low), including root causes, affected code locations, and actionable remediation steps.

## Verification Resources
- Test suite runner: ./.venv/bin/pytest tests/tier3_e2e_api/test_websocket_streaming.py -v
- Full E2E suite: ./.venv/bin/pytest tests/tier3_e2e_api/ -v

## Acceptance Criteria

### Implementation Quality
- [ ] _background_ws_tasks is completely removed from tars/api/routers/chat.py and tars/services/agent_chat.py.
- [ ] shutdown_background_tasks is exported from tars/orchestrator/nodes.py and invoked in tars/api/app.py during lifespan shutdown.
- [ ] Background knowledge extraction exceptions are logged with logger.error and exc_info=True.

### Test Validation
- [ ] ./.venv/bin/pytest tests/tier3_e2e_api/test_websocket_streaming.py -v passes with 0 failures.
- [ ] ./.venv/bin/pytest tests/tier3_e2e_api/ -v passes completely without regression.
- [ ] Socket disconnect resilience test asserts not task.cancelled() and task reaches completion.
- [ ] Multi-user isolation test confirms User B's task survives User A's socket closure.

### Production Audit Deliverable
- [ ] docs/PRODUCTION_READINESS_AUDIT.md is generated with findings categorized by severity, risk impact, and recommended fixes.
