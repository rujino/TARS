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

## 2026-09-05T14:45:16Z

TARS 프로덕션 안정화 및 분산 확장성 개선 (Phase 1: 신뢰성/보안/성능 11개 항목 & Phase 2: 중기 운영/관측 4개 항목 총 15개 과제 전면 적용)

Working directory: /home/ryuji/Workspace/TARS
Integrity mode: development

Reference document: `docs/PRODUCTION_READINESS_AUDIT.md` (Phase 1: Short-Term Hardening & Phase 2: Medium-Term Scalability)

## Requirements

### R1. Resource Pooling & Slicer Performance (RES-03, RES-04, PERF-01)
- SQLAlchemy 비동기 엔진에 연결 풀 파라미터(`pool_size=20`, `max_overflow=10`, `pool_timeout=30.0`, `pool_recycle=1800`, `pool_pre_ping=True`)를 설정하고 `Settings` 모델에 주입 가능하도록 구성해야 합니다.
- `ToolCAGManager`의 인메모리 캐시에 TTL(Time-to-Live) 타임스탬프 검증 및 만료 시 재계산 로직을 적용하여 유휴 메모리 누수를 방지해야 합니다.
- 다이내믹 슬라이서(`DynamicPromptSlicerEngine`)에서 후보 OKF 문서를 로딩할 때 순차 디스크 I/O를 `asyncio.gather`를 통한 병렬 배치 읽기로 전환하여 프롬프트 빌드 지연을 단축해야 합니다.

### R2. Streaming Concurrency & Client Disconnect Propagation (ASY-03, REL-02)
- Gemini SDK의 동기 스트림 반복자(`response_stream`)를 비동기 큐(`asyncio.Queue`) 기반 스레드 프로듀서 패턴으로 소비하여 동기 폴백 시 메인 `asyncio` 이벤트 루프 블로킹을 방지해야 합니다.
- SSE 및 WebSocket 실시간 스트리밍 엔드포인트에서 클라이언트 연결 해제(`request.is_disconnected()`) 상태를 감지하여, 탭 닫기나 네트워크 단절 시 백엔드 그래프 실행 및 LLM 토큰 생성을 즉시 중단해야 합니다.

### R3. Fault Tolerance & Realistic Timeout Budgets (REL-03, REL-04, REL-05)
- MCP 클라이언트(`AsyncMCPClient.call_tool`)에 네트워크 오류(`httpx.ConnectError`, 502/503/504) 시 Exponential Backoff 재시도(최대 2회) 및 실행 타임아웃(기본 10초) 가드를 추가해야 합니다.
- 프로액티브 대시보드 인사 생성(`ProactiveGreetingService`)에 엄격한 3.0초 타임아웃을 적용하고, 초과 또는 에러 시 지연 없이 결정론적 템플릿 인사로 즉시 폴백해야 합니다.
- 시맨틱 세션 토픽 전환 감지(`detect_topic_shift`)의 LLM 호출 타임아웃을 0.5초에서 현실적인 2.0초로 조정하여 클라우드 환경에서 기능이 무력화되지 않도록 보장해야 합니다.

### R4. Security, Layer Decoupling & Background Throttling (SEC-01, ARC-01, ASY-06)
- CORS 설정에서 와일드카드(`allow_origins=["*"]`)와 자격증명 허용(`allow_credentials=True`)의 동시 사용을 제거하고, `settings.cors_origins` 기반의 명시적 화이트리스트 도메인만 허용하도록 변경해야 합니다.
- 오케스트레이션 계층(`tars/orchestrator/nodes.py`)에서 API 계층(`tars/api/routers/chat.py`)을 동적 역참조하던 레거시 테스트 잔재를 완전히 제거하여 계층 순수성을 복원해야 합니다.
- 인프로세스 백그라운드 지식 추출 태스크에 바운디드 세마포어(`asyncio.Semaphore(10)`)를 적용하여 트래픽 스파이크 시 무제한 동시 추출로 인한 메모리/CPU 고갈을 방지해야 합니다.

### R5. Observability, Telemetry & Deep Health Probing (OBS-01, OBS-02, OBS-03, OBS-04)
- `CorrelationIdMiddleware`를 구현하여 모든 HTTP 요청에 `X-Correlation-ID` 헤더를 생성/전파하고 `contextvars` 및 로깅 필터를 통해 로그에 식별자를 기록해야 합니다.
- 어댑터 및 세션 전반에서 심각한 예외를 `logger.debug`로 은폐하던 패턴을 `logger.error(..., exc_info=True)` 및 `logger.warning`으로 표준화해야 합니다.
- 단순 200 반환인 `/health` 외에 실제 DB 연결(`SELECT 1`) 및 파일 스토리지 접근성을 실시간 검증하고 상태에 따라 200/503을 반환하는 `/health/readiness` 딥 프로브를 추가해야 합니다.
- `prometheus_client` 기반의 표준 `/metrics` 엔드포인트를 구현하여 요청 지연시간, 에러율, 서킷 브레이커 상태 등을 관측할 수 있도록 해야 합니다.

## Verification Resources
- 감사 보고서: `docs/PRODUCTION_READINESS_AUDIT.md` (Phase 1, Phase 2 상세 가이드)
- 기존 테스트 스위트: `tests/tier1_unit/`, `tests/tier2_integration/`, `tests/tier3_e2e_api/`, `tests/orchestrator/`
- 가상환경 도구: `./.venv/bin/pytest`, `./.venv/bin/mypy`, `./.venv/bin/ruff`

## Acceptance Criteria

### Resource Pooling & Slicer
- [ ] SQLAlchemy 비동기 엔진 생성 시 `pool_pre_ping=True`, `pool_size`, `max_overflow`, `pool_recycle`이 적용됨이 단위 테스트로 확인되어야 합니다.
- [ ] `ToolCAGManager`에서 캐시 수명이 지난 경우 번들이 갱신되는 동작이 검증되어야 합니다.
- [ ] 슬라이서의 문서 로딩이 `asyncio.gather`로 병렬 처리되며 기존 슬라이싱 테스트가 정상 통과해야 합니다.

### Streaming & Disconnect Propagation
- [ ] 동기 Gemini 스트림 폴백 시 비동기 큐를 통해 블로킹 없이 청크가 전달되어야 합니다.
- [ ] SSE 스트리밍 도중 클라이언트 단절 시 루프가 중단되고 로그에 기록되어야 합니다.

### External Resiliency & Timeouts
- [ ] MCP 툴 네트워크 일시 에러 발생 시 재시도 로직이 동작하고 타임아웃이 초과되면 에러 결과가 반환되어야 합니다.
- [ ] Greeting LLM 호출이 3초를 초과하면 즉시 템플릿 인사말이 반환되어야 합니다.
- [ ] 토픽 감지 타임아웃 기본값이 2.0s로 설정되어 정상 응답 처리가 가능해야 합니다.

### Security, Clean Architecture & Throttling
- [ ] CORS 헤더가 설정된 도메인 목록에 대해서만 응답을 허용해야 합니다.
- [ ] `nodes.py`에서 `chat.py`로의 임포트/참조가 완전히 제거되어야 합니다.
- [ ] 백그라운드 지식 추출이 세마포어(최대 10개 동시 실행)를 통해 스로틀링되어야 합니다.

### Observability & Metrics
- [ ] API 요청 시 `X-Correlation-ID` 헤더가 응답에 포함되어야 합니다.
- [ ] `/health/readiness` 호출 시 DB 및 스토리지 점검 상태와 함께 200 또는 503 코드가 올바르게 반환되어야 합니다.
- [ ] `/metrics` 엔드포인트에서 프로메테우스 형식의 메트릭이 정상 조회되어야 합니다.

### Stability & Regressions
- [ ] 전체 테스트 스위트(`pytest`)가 100% 통과해야 합니다.
- [ ] mypy 타입 검사 및 ruff 린트 검사가 오류 0건으로 통과해야 합니다.


