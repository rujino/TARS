# TARS 시스템 아키텍처 정의서 (ARCHITECTURE.md)

## 1. 시스템 개요 (System Overview)
TARS 프로젝트는 **"오브젝트 스토리지(지식 원본) + RDBMS(메타데이터) + OKF(표준 지식 규격)"**의 삼위일체(Trinity) 구조와 **LangGraph 기반 ReAct 에이전트 오케스트레이션**을 융합한 프로덕션급 멀티 테넌트 AI 동반자 플랫폼입니다.

동적으로 변화하는 사용자 지식(`llmwiki`)은 파일 스토리지의 순수 **OKF 마크다운 문서**로 보관하여 벤더 종속성을 원천 차단하고, DB(PostgreSQL 16)는 **초경량 메타데이터(Path, User, Auth, Session)**만을 관리하여 극상의 성능과 데이터 무결성을 보장합니다.

---

### 2. K3s 기반 분리형 스토리지 & 하이브리드 오케스트레이션 다이어그램

```text
 [ 📱 클라이언트 (Web PWA / Mobile Browser / On-Device TTS & STT) ]
     │
     │ (HTTPS / WSS 보안 통신, JWT 인증, X-Correlation-ID 추적)
     ▼
 ┌─────────────────────────── [ ☸️ K3s Production Edge Cluster ] ───────────────────────────┐
 │                                                                                         │
 │   [ 🌐 Ingress & Security Layer (Traefik + cert-manager) ]                              │
 │     └─ Let's Encrypt 자동 SSL/TLS 종단, HTTP->HTTPS 리다이렉트, SSE/WebSocket 무지연 프록시  │
 │                                                                                         │
 │   ┌─────────────────────── [ 🚀 tars-backend (3 Replicas) ] ────────────────────────┐   │
 │   │                                                                                 │   │
 │   │   [ 1. LangGraph StateGraph ReAct Pipeline ]                                    │   │
 │   │     ├─ session_node     : 시간 감쇄(15m/2h) 라우팅, 페르소나 로드, 리셋 명령 감지    │   │
 │   │     ├─ reset_node       : 자연어 리셋 시 즉각 아카이빙 및 세션 초기화 메시지 생성│   │
 │   │     ├─ slicer_node      : OKF 5-Factor 점수화 기반 지식 원문 프롬프트 동적 주입 │   │
 │   │     ├─ prompt_node      : 프롬프트 인젝션 방어 태깅 & 지시문 계층화 시스템 프롬프트  │   │
 │   │     ├─ llm_node         : Gemini 고지능 발화(100% User-Facing) & Function Calling │   │
 │   │     ├─ tool_node        : MCP / Google Workspace 도구 병렬 실행 & 타임아웃 격리 │   │
 │   │     └─ postprocess_node : 대화 턴 DB 영속화 & 비동기 지식 추출 워커 디스패치    │   │
 │   │                                                                                 │   │
 │   │   [ 2. StreamBridge & Event Dispatcher ]                                        │   │
 │   │     └─ stream_start ➔ token ➔ tool_start ➔ tool_result ➔ stream_end ➔ done        │   │
 │   │                                                                                 │   │
 │   │   [ 3. Background Knowledge Extractor (자가 진화 루프) ]                        │   │
 │   │     └─ 대화 속 중요 정보 감지 ➔ 새 OKF 파일 자동 생성 ➔ 스토리지/DB 원자적 저장  │   │
 │   │     └─ 소켓 종료와 무관한 완전 격리 실행 & FastAPI Lifespan Graceful Drain (5s) │   │
 │   │                                                                                 │   │
 │   │   [ 4. Telemetry & Observability ]                                              │   │
 │   │     ├─ Request Correlation ID ContextVar 전파 및 구조화 JSON 로깅               │   │
 │   │     ├─ Liveness / Readiness 다차원 헬스체크 (`/health/live`, `/health/ready`)   │   │
 │   │     └─ Langfuse 대화 및 툴 호출 전과정 트레이싱                                │   │
 │   └─────────────────────────────────────────────────────────────────────────────────┘   │
 │                                    │                    │                               │
 │           (tars-storage-pvc / tars-data-pvc)     (tars-db:5432 asyncpg)                 │
 │                                    ▼                    ▼                               │
 │   [ 📁 Storage Layer (PVC 10Gi) ]     [ 🗄️ Database Layer (tars-db 10Gi PVC) ]            │
 │   사용자별 OKF 마크다운 원본 문서     PostgreSQL 16: 회원/설정/세션/메타데이터           │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
 [ 🦙 로컬 SLM (llama-server) ]                [ ☁️ Google Cloud (Gemini API) ]
 (GGUF 경량 C++: 의도분류/전처리)               (페르소나 발화 100% & Function Calling)
 └─────────────────────────────────── 서킷 브레이커 & 상호 Fallback ─────────────────────────┘
```

---

## 3. 핵심 시스템 엔지니어링 원칙 (Core Engineering Principles)

1. **오브젝트 스토리지 + RDBMS 분리형 멀티테넌트 아키텍처 (Enterprise Storage Pattern)**:
   - 지식 원본은 파일 스토리지(`.md`)에, 메타데이터는 DB에 분리 저장하여 **Zero Data Loss(데이터 무결성)**와 **초고속 쿼리 성능**을 동시에 달성.
2. **OKF (Open Knowledge Format 1.0) 표준 엔진**:
   - YAML Frontmatter + Markdown 구조를 직접 파싱/검증하는 전용 엔진(`tars.core.okf`)을 구축하여 완벽한 Vendor-Agnostic 지식 생태계 실현.
3. **LangGraph StateGraph 기반 ReAct 파이프라인**:
   - 절차적 모놀리식 코드를 배제하고 `session` ➔ `slicer` ➔ `prompt` ➔ `llm` ⇄ `tool` ➔ `postprocess`로 이어지는 순수 노드 상태 머신으로 일원화.
4. **프롬프트 보안 및 상태 격리 (State Isolation & Prompt Injection Defense)**:
   - `system_prompt`를 `messages` 리스트와 완전히 격리 보관하여 DB 대화 기록 오염을 방지.
   - 외부 동적 지식과 도구 반환값은 `<user_knowledge_context>` 및 `[Tool Result]` 경계 태그로 캡슐화하고 탈출 문자를 이스케이프 처리하며, `[SYSTEM DIRECTIVE PRIORITY]` 지침을 강제 적용.
5. **하이브리드 추론 & 양방향 회로 차단기 (Hybrid Inference & Circuit Breaker)**:
   - 페르소나 발화 및 툴 파싱은 Cloud Gemini가 전담하고, 빠른 의도 분류는 로컬 `llama.cpp`가 전담.
   - 로컬 SLM 장애 시 Gemini로 즉시 자동 Fallback하며, 클라우드 장애 상황에도 안정적인 에러 핸들링 보장.
6. **백그라운드 태스크 수명주기 격리 & Graceful Shutdown**:
   - 프레젠테이션 계층(WebSocket 라우터)과 백그라운드 지식 추출 태스크의 수명주기를 완전 분리. 클라이언트 연결 종료 시에도 타 유저 태스크 취소 없이 정상 완결.
   - 서버 종료(SIGTERM) 시 FastAPI `lifespan` 컨텍스트 매니저를 통해 실행 중인 백그라운드 작업을 5초간 대기(`asyncio.wait`) 후 안전 종료(Graceful Drain).
7. **관측성 & 분산 추적 (Telemetry & Probes)**:
   - 요청마다 고유한 `correlation_id`를 발행하고 `ContextVar`를 통해 비동기 태스크 전반에 걸쳐 전파하여 구조화 로깅 지원.
   - K3s 파드 상태 점검을 위한 Liveness(`live`) 및 DB/스토리지 연결성을 실질 검증하는 Readiness(`ready`) 엔드포인트 제공.
8. **정적 CAG(툴 스키마 캐싱) + 5-Factor 동적 OKF 슬라이싱**:
   - 대형 툴 스키마 JSON은 캐싱하여 비용과 속도를 최적화하고, 대화 맥락과 관련된 OKF 문서는 5가지 가중치 기반으로 1,500 토큰 이내로 정밀 패킹.
9. **음성 우선 능동 대화 & 스마트 세션 라이프사이클 (Voice-First Session Architecture)**:
   - **App-Launch Greeting**: 앱 실행 즉시 시간대/미접속 시간/이전 맥락/OKF 지식을 결합해 1~2문장의 능동 오프닝을 먼저 발화하고 마이크 리스닝 모드로 즉시 전환.
   - **Dual-Layer Memory**: 단기 작업 기억(Session/Context Window)은 시간 감쇄 및 자연어 리셋 명령으로 기민하게 초기화하고, 장기 기억은 비동기 OKF 파일로 영구 보존.
10. **사용자별 토글형 원클릭 플러그인 허브 (User-Scoped Toggleable Tool Hub)**:
    - 사용자 계정별로 활성화된 도구 목록에 맞춰 세션별 `ToolRegistry`를 동적으로 조립 및 주입. 도구 실행 시 10초 타임아웃 격리 적용.
11. **K3s 기반 선언적 엣지 오케스트레이션 (Lightweight Production Orchestration)**:
    - 마스터 메모리 1GB 미만의 초경량 오버헤드로 Deployment, Service DNS, PVC 영구 볼륨, Secret 분리, Traefik/cert-manager를 통한 HTTPS/WSS 자동화 완결.
12. **On-Device Web Speech TTS & Client Performance**:
    - 온디바이스 음성 합성/인식으로 백엔드 GPU/서버 부하 0% 달성 및 실시간 스트리밍 경험 제공.


