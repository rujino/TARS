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



## 2026-09-06T17:18:19Z

Implement an interactive MCP server and tool management interface in TARS, including a sidebar accordion list, tool active/disabled toggles, Google OAuth2 redirect account linking, and LangGraph agent runtime filtering.

Working directory: /home/ryuji/Workspace/TARS
Integrity mode: demo

## Requirements

### R1. MCP Server & Tool Discovery Accordion UI
Add a scrollable section in the TARS HUD sidebar displaying connected MCP servers and builtin Google Workspace integrations. Each server must render as an accordion item showing its connection status (connected, offline, mock), active tool count, and a collapsible list of tools.

### R2. Tool Activation/Deactivation & Agent Runtime Filtering
Provide per-tool toggle switches in the UI to enable or disable individual tools. Persist disabled tool preferences in the database (`TARSSettings`). In the LangGraph ReAct agent pipeline (`llm_node` and `tool_node`), disabled tools must be excluded from LLM function calling schema declarations and blocked from execution.

### R3. Account Linking & Configuration Modal (Google OAuth2 Redirect)
Implement a HUD modal dialog accessible from server and tool entries. For Google Workspace, support an OAuth2 authorization redirect flow (authorization URL generation, callback code exchange, and refresh token storage), along with a deterministic one-click Mock linking toggle for offline testing. For MCP servers, allow inspecting and updating server transport endpoints, headers, and running connection tests.

### R4. Automated Testing & Verification
Implement automated unit and integration tests covering the tool management REST API, ToolRegistry schema filtering, OAuth2 redirect and callback endpoints, and agent runtime isolation for disabled tools.

## Acceptance Criteria

### API & Tool Registry
- [ ] `GET /api/v1/tools/servers` returns all registered servers and their tools with accurate active/disabled states.
- [ ] `PATCH /api/v1/tools/{tool_name}/toggle` toggles and persists the tool's enabled state in `TARSSettings`.
- [ ] `ToolRegistry.export_gemini_declarations()` excludes disabled tools when requested by the agent runtime.
- [ ] `tool_node` blocks execution of disabled tools and returns an informative error message.

### Account Linking & OAuth2
- [ ] `GET /api/v1/tools/auth/google/url` returns a valid Google OAuth2 authorization URL with required scopes.
- [ ] `GET /api/v1/tools/auth/google/callback` exchanges authorization code for tokens and updates user credentials in the database.
- [ ] `POST /api/v1/tools/auth/google/mock-link` toggles mock Google credentials for offline development.

### UI & Interaction
- [ ] TARS sidebar includes a scrollable `[ MCP & TOOLS ]` section below the persona controls.
- [ ] Accordion collapses and expands tool lists smoothly with visual state indicators (status dot, active badge).
- [ ] Each tool row displays an active/disabled status badge and interactive toggle switch.
- [ ] Clicking a server or tool opens the HUD configuration modal for OAuth linking and settings.

### Test Suite
- [ ] All new tests in `tests/tier1_unit/test_tools_management.py` pass.
- [ ] All existing tier 1 unit tests pass (`.venv/bin/pytest tests/tier1_unit/`).

## 2026-09-16T23:25:07Z

TARS 기존 레거시 테스트용 프론트엔드를 전면 제거하고 기획서 스펙에 맞춘 '베라 & 미우 듀얼 메이드 단톡방 클라이언트'로 완전히 새로 구축하며, 백엔드의 가짜 하드코딩 대사(Mock/Fallback f-strings)를 전면 제거하고 실제 LLM 런타임 및 WebSocket 파이프라인에 완전하게 연결(Wiring)합니다.

Working directory: /home/ryuji/Workspace/TARS
Integrity mode: development

## Reference Material
- 기획서 1부 (인지 내면 & ToM): `docs/COGNITIVE_COMPANION_PLAN.md`
- 기획서 2부 (사회성 & 듀얼 메이드 단톡방): `docs/COGNITIVE_COMPANION_PLAN_PART2.md`
- 기획서 3부 (분산 런타임 & 초저지연 인프라): `docs/COGNITIVE_COMPANION_PLAN_PART3.md`

## Requirements

### R1. `companion.py` 내 가짜 하드코딩 대사(Mock Fallback) 전면 영구 제거 및 실제 듀얼 LLM 추론 강제
- `_generate_character_response()` 내의 하드코딩된 f-string 대사 템플릿("~다냥!", "수석 메이드 베라입니다" 등)을 완전히 제거합니다.
- 베라(System 2)와 미우(System 1)는 반드시 `PersonaRegistry`의 고유 시스템 프롬프트(`VERA_SYSTEM_PROMPT_TEMPLATE`, `MIU_SYSTEM_PROMPT_TEMPLATE`)와 중앙 무의식의 ToM(`master_state`), 서사 맥락(`context_summary`), 캐릭터별 직전 감정 여운(`prev_vibe`), 단톡방 상호작용 시각(`perspective_context`)을 주입받아 `HybridLLMRouter`(Gemini / SLM)를 통해 각각 독립적으로 실제 추론 및 발화하도록 강제합니다.
- 가짜 텍스트 반환을 원천 금지하며, LLM 호출 실패 시 숨기지 않고 명확한 에러 핸들링 및 재시도/디그레이데이션 경로를 타도록 합니다.

### R2. 실제 서비스 경로(`AgentChatService` & WebSocket/SSE)에 `create_companion_graph` 전면 와이어링
- `tars/domains/chat/services/agent_chat.py`의 `stream_chat()`이 더 이상 레거시 단일 챗봇 그래프(`create_chat_graph`)를 타지 않고, 베라 & 미우 듀얼 컴패니언 그래프(`create_companion_graph`)를 직접 실행하도록 교체 연결합니다.
- `companion_dispatch_node`에서 방출되는 토큰 및 이벤트에 화자 식별자(`speaker: "vera" | "miu"`), 아바타 경로, 세대 번호(`turn_epoch`), 턴 상태 메타데이터를 필수 탑재하여 실시간 스트리밍으로 흘려보냅니다.
- `HybridSessionTurnLock`과 `PrefetchBufferQueue`가 실제 웹소켓 스트림과 유기적으로 결합되어, 1차 화자 발화 중 2차 화자 선행 생성 및 0.2초 지터 전환, Barge-in 인터럽트 시 0ms 즉시 토큰 드롭이 실 서비스에서 작동하도록 연결합니다.

### R3. 카톡 읽음 확인(Read Receipt) 및 실시간 타이핑 인디케이터 프로토콜 구현
- 기획서 3부 4.2절 명세에 따라, 사용자 메시지 전송 즉시 노란 숫자 `2`가 렌더링되고, 베라는 0.05초 만에 읽음(`{"type": "read_receipt", "reader": "vera", "unread_count": 1}`), 미우는 0.3~0.5초 시간차 지터 후 읽음(`{"type": "read_receipt", "reader": "miu", "unread_count": 0}`)을 방출하는 실시간 프로토콜을 백엔드와 프론트엔드에 양방향 구현합니다.
- 2차 화자 선행 생성(프리페치) 트리거 발동 시 `{"type": "typing_indicator", "sender": "miu", "status": "active"}`를 클라이언트로 송출하여 "🐾 미우가 발을 동동 구르며 타자 치는 중..." 겹침 타이핑 연출을 제공합니다.

### R4. 프론트엔드(`tars/static`) 전면 제거 및 베라 & 미우 단톡방 전용 클라이언트 신규 구축
- 기존 레거시 단일 TARS 챗봇 UI를 완전히 제거하고, 기획서 2부/3부에 부합하는 모던 웹 클라이언트(`index.html`, `style.css`, `app.js`, `chat.js`)를 신규 작성합니다.
- **헤더 & 단톡방 참여자**: 베라(🧊 수석 메이드)와 미우(🐾 견습 고양이 메이드)의 프로필 및 실시간 온라인/타이핑 상태 표시.
- **좌측 사이드바**: 제미나이 스타일의 일자별(오늘 / 어제 / 지난 7일 / 지난 30일 / 이전 대화) 대화 목록 아코디언 및 `[+ New Chat]` 버튼.
- **단톡방 메인 뷰**:
  - 사용자 메시지(우측 말풍선, 노란 숫자 읽음 카운터 `2` -> `1` -> 사라짐).
  - 베라의 메시지(좌측, 베라 아바타 및 수석 메이드 뱃지, 격조 높은 하십시오체 말풍선).
  - 미우의 메시지(좌측, 미우 아바타 및 고양이 뱃지, 귀여운 1~2문장 말풍선).
  - 실시간 토큰 스트리밍 시 화자별 전용 말풍선에서 타이핑 커서가 부드럽게 출력.
- 과거 세션 클릭 시 과거 대화 턴들을 화자별 아바타/이름과 함께 정확히 복원하고 세션 전환 후 대화 지속 가능.

## Acceptance Criteria

### Authentic Dual LLM Inference (No Mocks)
- [ ] `companion.py`에 어떠한 하드코딩된 대사 템플릿 f-string도 존재하지 않아야 한다 (`_generate_character_response` 완전 제거).
- [ ] 베라와 미우의 발화는 각각 `HybridLLMRouter`를 통해 고유 시스템 프롬프트와 ToM 상태를 바탕으로 독립 실행된 실제 LLM 응답이어야 한다.

### Production Runtime Wiring
- [ ] `AgentChatService.stream_chat()`이 실제 실행 시 `create_companion_graph`를 구동함을 확인하는 E2E 테스트가 통과해야 한다.
- [ ] WebSocket `/api/v1/chat/ws` 스트리밍 프레임에 `speaker` ("vera" 또는 "miu"), `turn_epoch`가 명확히 포함되어 전송되어야 한다.

### Group Chat & Read Receipt Protocol
- [ ] 사용자 메시지 인입 시 읽음 확인 이벤트가 베라(즉시)와 미우(지터) 순으로 정상 발행되어야 한다.
- [ ] 프리페치 트리거 시 2차 화자의 `typing_indicator` 웹소켓 프레임이 클라이언트로 전송되어야 한다.

### Redesigned Frontend UI
- [ ] `tars/static`에 더 이상 `TARS // AI` 단일 챗봇 텍스트나 레거시 컴포넌트가 남지 않고, 베라 & 미우 단톡방 인터페이스가 렌더링되어야 한다.
- [ ] 사용자 메시지 우측 배치, 베라/미우 메시지 좌측 분리 및 각자의 아바타와 이름이 정상 표기되어야 한다.
- [ ] 좌측 사이드바에 `[+ New Chat]` 버튼과 일자별 그룹 목록이 작동하며 세션 전환 및 과거 화자별 대화 복원이 원활히 이루어져야 한다.

