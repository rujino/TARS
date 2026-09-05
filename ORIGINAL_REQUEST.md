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

## 2026-09-05T10:07:11Z

TARS 프로덕션 배포 차단 결함(Phase 0: P0 Immediate Hardening 7개 항목)을 해결하여 동시성 안전성, 리소스 수명주기, 클라우드 장애 복원력, 이벤트 루프 응답성을 보장하는 엔터프라이즈급 프로덕션 수준으로 시스템을 개선합니다.

Working directory: /home/ryuji/Workspace/TARS
Integrity mode: development

Reference document: `docs/PRODUCTION_READINESS_AUDIT.md` (Phase 0: Immediate Deployment Blockers)

## Requirements

### R1. Concurrency & Background Task Safety (ASY-01, ASY-04, ASY-05)
- WebSocket 연결 종료가 동일 프로세스 내 다른 사용자의 진행 중인 백그라운드 지식 추출 작업을 취소하거나 중단시키지 않아야 합니다.
- WebSocket 세션 아카이빙(시간 경과, 토픽 전환, 강제 초기화 등) 발생 시에도 백그라운드 지식 추출 작업이 누락 없이 비동기 작업 큐로 디스패치되어야 합니다.
- 백그라운드 워커는 `asyncio.CancelledError`를 정상적으로 전파하여 협력적 취소를 지원하고, 처리되지 않은 예외는 스택 트레이스와 함께 에러 레벨로 기록되어야 합니다.
- 애플리케이션 종료(lifespan shutdown) 시 진행 중인 백그라운드 작업들을 유예 시간 내에 정상 드레이닝(graceful drain)해야 합니다.

### R2. Resource & Client Lifecycle Management (RES-01, RES-02)
- 요청마다 `httpx.AsyncClient`나 도구 인스턴스가 무분별하게 생성 및 누수되지 않도록 도구 레지스트리와 클라이언트 수명주기를 애플리케이션 수명주기(lifespan)에 맞춰 싱글톤으로 관리하고 비동기 정리(`aclose`)를 제공해야 합니다.
- FastAPI 애플리케이션 종료 시 SQLAlchemy 비동기 엔진(`AsyncEngine`)을 안전하게 dispose하여 연결 풀 소켓 누수를 원천 차단해야 합니다.

### R3. Cloud LLM Resilience & Bidirectional Circuit Breaker (REL-01)
- 외부 Cloud Gemini API 장애(네트워크 에러, 429 Quota, 5xx 서버 에러, 타임아웃 등) 발생 시 전체 대화가 중단되지 않도록 서킷 브레이커(Closed/Open/Half-Open) 메커니즘을 구축해야 합니다.
- Gemini 호출 실패 또는 서킷 차단 시 로컬 보조 코어(Local SLM)로 즉시 자동 폴백(fallback)하여 대화 연속성을 보장하고, 사용자에게 보조 코어 동작 상태를 전달해야 합니다.

### R4. Event Loop Async Hygiene for Authentication (ASY-02)
- Bcrypt 비밀번호 해싱 및 검증과 같은 CPU 집약적 연산이 메인 `asyncio` 이벤트 루프 스레드를 차단하지 않도록 비차단(non-blocking) 스레드 풀 오프로딩 처리를 보장해야 합니다.

## Verification Resources
- 감사 보고서 및 검증 절차: `docs/PRODUCTION_READINESS_AUDIT.md` (Section 3, 4, 5)
- 기본 회귀 테스트 스위트: `tests/tier3_e2e_api/`, `tests/tier1_unit/`
- 가상환경 실행기: `./.venv/bin/pytest` 및 `python`

## Acceptance Criteria

### Concurrency & Task Safety
- [ ] 단일 WebSocket 연결 해제 시 다른 세션의 백그라운드 태스크가 취소되지 않음이 단위/통합 테스트로 검증되어야 합니다.
- [ ] WebSocket 환경에서 세션 아카이빙 시 지식 추출 태스크가 정상 스케줄링됨이 확인되어야 합니다.
- [ ] 백그라운드 워커에서 `asyncio.CancelledError`가 재발생(re-raise)되고 일반 예외는 `logger.error(..., exc_info=True)`로 추적되어야 합니다.
- [ ] 애플리케이션 종료 시 백그라운드 작업 드레이닝 루틴이 동작해야 합니다.

### Resource & Connection Cleanup
- [ ] `ToolRegistry` 및 관련 HTTP 클라이언트 어댑터들이 애플리케이션 종료 시 `aclose`를 통해 소켓 디스크립터를 정상 해제해야 합니다.
- [ ] 애플리케이션 lifespan 종료 후 `close_db()`가 호출되어 DB 커넥션 풀이 정상 폐기되어야 합니다.

### Cloud LLM Circuit Breaker & Fallback
- [ ] Gemini API 연속 실패 시 서킷 브레이커가 OPEN 상태로 전이되어야 합니다.
- [ ] 서킷이 OPEN 상태이거나 Gemini 예외 발생 시 로컬 SLM 어댑터로 자동 폴백 응답이 생성되어야 합니다.
- [ ] 복구 대기 시간 후 HALF_OPEN 상태에서 시험 요청 성공 시 CLOSED로 복구되어야 합니다.

### Async Authentication Hygiene
- [ ] 회원가입 및 로그인 라우트에서 bcrypt 해싱 및 검증이 이벤트 루프를 블로킹하지 않고 비동기로 처리되어야 합니다.

### Regression & Stability
- [ ] 기존 전체 E2E 테스트 스위트(`pytest tests/tier3_e2e_api/`)가 실패 없이 100% 통과해야 합니다.
- [ ] 신규 P0 방어 로직에 대한 검증 테스트가 추가되거나 기존 테스트에 포함되어 성공해야 합니다.

