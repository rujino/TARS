# TARS: 위트 있는 AI 동반자 & 에이전트 제품 명세서 (PRD)

## 1. 프로젝트 비전 및 시스템 개요

- **비전**: 영화 *인터스텔라*의 TARS처럼, 신뢰할 수 있는 문제 해결 능력과 **유머 지수(90%) / 솔직함(95%)**을 갖춘 나만의 AI 동반자.
- **운영 상태**:
  - **일상 대화 & 실시간 음성 인터랙션**: WebSocket 및 SSE 실시간 양방향 스트리밍과 클라이언트 On-Device Web Speech TTS/STT를 통한 TARS 고유의 음성 피드백 가동.
  - **오브젝트 스토리지 + DB + OKF 삼위일체 지식 베이스**: 분리형 스토리지(File PVC + PostgreSQL 16)와 OKF(Open Knowledge Format 1.0) 표준 엔진 기반 5-Factor 동적 슬라이싱 및 대화 기반 비동기 자가 진화 루프 완결.
  - **LangGraph ReAct 에이전트 오케스트레이션**: 단일 `StateGraph` 파이프라인에서 세션 분기, 프롬프트 인젝션 방어벽, Gemini Function Calling, MCP 및 Google Workspace 도구 연동, 턴 영속화 수행.
  - **프로덕션 엣지 인프라**: K3s(경량 쿠버네티스) + Traefik Ingress + cert-manager (Let's Encrypt SSL/TLS), 로컬 SLM(`llama.cpp`), 텔레메트리(Correlation ID, 구조화 로깅, 상태 프로브), Graceful Shutdown 완결.

---

## 2. 노드 및 하드웨어 구성

1. **Host Server (K3s Edge Cluster / Production Node)**:
   - **K3s 기반 선언적 컨테이너 오케스트레이션**:
     - **FastAPI 백엔드 파드 (`tars-backend`, 3 Replicas)**:
       - **OKF Engine**: YAML Frontmatter 파싱 ➔ 지식 지도 구성 ➔ 5-Factor 동적 슬라이싱 주입.
       - **정적 툴 CAG**: 페르소나 및 대형 툴 스키마 JSON 인메모리 캐싱.
       - **LangGraph ReAct Orchestrator**: 세션 라우팅 / SLM 전처리 / Gemini 고지능 발화 / Tool 호출 루프 / 후처리 및 영속화 단일 파이프라인.
       - **비동기 지식 추출기**: 대화 속 중요 사실/선호도 감지 ➔ 새 OKF 파일 자동 생성 ➔ 스토리지/DB 원자적 저장.
       - **운영 안정성**: Liveness/Readiness 헬스체크 (`/health/live`, `/health/ready`), Correlation ID 추적, 서버 종료 시 백그라운드 태스크 완결(Graceful Drain, 5초 타임아웃).
     - **Storage Layer (`tars-storage-pvc` 10Gi, `tars-data-pvc` 5Gi)**:
       - K3s `local-path` 기반 사용자별 OKF 마크다운 문서 원본 영구 보존 (`/app/storage/users/{user_id}/wikis/*.md`).
     - **DB Layer (`tars-db`, PostgreSQL 16 Deployment + 10Gi PVC)**:
       - 회원 정보, TARS 파라미터, 파일 경로(`file_path`) 메타데이터, 대화 세션/이력 관리 및 Alembic 비동기 마이그레이션 (`asyncpg`).
     - **로컬 SLM 추론 엔진 (`llama-server` / `llama.cpp`)**:
       - GGUF C++ 경량 런타임 기반 의도 분류, 쿼리 전처리, 키워드 추출 (OpenAI 호환 API `/v1`, 서킷 브레이커 자동 Fallback 연동).
     - **Traefik Ingress + cert-manager**:
       - Let's Encrypt 자동 SSL/TLS 인증서 발급/갱신 (HTTPS/WSS 무중단 종단 및 SSE/WebSocket 실시간 스트리밍).
     - **보안 & 환경 분리 (ConfigMap & Secret)**:
       - 민감 키(JWT Secret, Gemini API Key, DB Password)를 Kubernetes Secret으로 분리 격리 및 안전한 CORS 정책 적용.
   - **Langfuse & Telemetry Layer**: Correlation ID 기반 유저 세션별 대화, 툴 호출, 모델 지연 시간 및 토큰 소모량 추적.

2. **Client Interface (Web PWA / Mobile Browser)**:
   - 반응형 Sci-Fi HUD 인터페이스 및 PWA(Service Worker, Manifest) 지원.
   - JWT 인증 기반 보안 세션 수립 및 WebSocket/SSE 실시간 스트리밍.
   - **On-Device TTS/STT**: Web Speech API 기반 TARS 톤(피치/속도 조정) 실시간 음성 발화 및 음성 입력 지원 (서버 부하 0%).

---

## 3. 핵심 기능 구현 명세 (Core Features Implementation)

### 3.1. 오브젝트 스토리지 + DB + OKF 지식 아키텍처
- **지식 원본 영속화**: 순수 OKF 포맷(`.md`)으로 파일시스템/스토리지(PVC)에 보관하여 벤더 독립성 및 Git 호환성 확보.
- **초경량 메타데이터 DB**: PostgreSQL 16은 `user_id`, `okf_id`, `file_path`, `updated_at` 메타데이터만 관리하여 극상의 성능 보장.
- **5-Factor 동적 슬라이서**: Context Relevance, Importance, Type, Relations, Recency 5개 가중치 기반으로 질문에 가장 적합한 OKF 지식을 최대 1,500 토큰 내로 패킹하여 프롬프트에 주입.

### 3.2. 대화 기반 자가 학습 OKF 지식 베이스
- **대화 속 자동 지식 포착**: 사용자가 대화 중에 언급한 새로운 선호도, 규칙, 일정 정보를 TARS가 자동 추출.
- **OKF 파일 자동 생성**: `source: "auto_extracted"` 태그와 함께 표준 YAML Frontmatter + Markdown 본문 구조로 파일 생성.
- **비동기 백그라운드 완결**: 클라이언트 소켓이 종료되더라도 작업이 중단되지 않는 격리된 비동기 태스크로 DB/스토리지 원자적 동기화 보장.

### 3.3. 데이터베이스 & 회원 관리 (RDBMS & Auth)
- **비동기 보안 인증**: `asyncio.to_thread` 기반 non-blocking Passlib(bcrypt) 비밀번호 해싱 및 JWT 액세스 토큰 발급.
- **개인화 설정 저장**: 유저별 선호 `humor_level`(기본 90%), `honesty_level`(기본 95%), TARS 모드(`companion` / `work`) 저장 및 즉각 반영.
- **대화 이력 보존**: 세션별 대화 메시지 DB 영속화 및 이전 대화 맥락 복원.

### 3.4. LangGraph ReAct 오케스트레이션 & 도구 생태계
- **단일 StateGraph 파이프라인**:
  - `session_node` ➔ (`is_reset` 분기) ➔ `slicer_node` ➔ `prompt_node` ➔ `llm_node` ⇄ `tool_node` (ReAct 루프) ➔ `postprocess_node`
- **하이브리드 추론 분리 & 양방향 서킷 브레이커**:
  - **사용자 대화 응답 (100%)**: Google Gemini 전담 (TARS 고유 페르소나 및 도구 결과 융합 발화).
  - **경량 내부 추론**: 로컬 SLM(`llama.cpp`) 전담 (의도 분류, 쿼리 전처리).
  - **자동 Failover**: 로컬 SLM 지연/장애 시 Gemini로 즉시 Fallback, 반대로 외부 Gemini 장애 시에도 로컬 대응 가능한 서킷 브레이커 탑재.
- **확장형 도구 & MCP 생태계**:
  - Anthropic 표준 JSON-RPC 2.0 MCP Client (HTTP, SSE, stdio, Mock 트랜스포트 지원).
  - Google Workspace(Calendar, Gmail) 네이티브 도구 어댑터.
  - 사용자별 활성화 목록에 따른 동적 `ToolRegistry` 세션 주입.
  - 도구 실행 타임아웃 격리(10초) 및 에러 시 TARS 데드팬 위트 Fallback.
- **프롬프트 보안 및 인젝션 방어벽**:
  - `system_prompt`와 `messages` 상태를 엄격히 분리하여 DB 대화 기록 오염 방지.
  - 동적 지식 및 도구 실행 결과를 XML 경계 태그(`<user_knowledge_context>`, `[Tool Result]`)로 격리하고 지시문 우선순위 계층화(`[SYSTEM DIRECTIVE PRIORITY]`) 적용.

### 3.5. 음성 인터랙션 & 스마트 세션 관리
- **앱 실행 시 선제 화제 제시 (App-Launch Proactive Greeting)**:
  - 앱 접속 시 빈 화면 대기 대신 접속 시간대, 미접속 공백 기간, 이전 대화 맥락, OKF 지식을 종합하여 1~2문장의 능동 오프닝 발화 생성.
- **스마트 세션 라이프사이클**:
  - **시간 경과 감쇄**: 15분 이내 세션 유지, 15분~2시간 브릿지 요약 후 분기, 2시간 초과 시 신규 세션 분기.
  - **자연어 명령 제어**: "TARS, 리셋해", "새로운 주제야" 입력 시 즉각 아카이빙 후 세션 초기화.
  - **의미론적 주제 전환**: 대화 흐름 급변 감지 시 세션을 분기하고 이전 맥락을 OKF 장기 기억으로 이관.
- **On-Device TTS/STT**: 텍스트 스트리밍 수신과 동시에 브라우저 음성 합성 엔진으로 발화하여 서버 자원 소모 제로화.

---

## 4. 시스템 사양 요약 (System Specifications)

| 구분 | 사양 및 구성 |
| :--- | :--- |
| **백엔드 프레임워크** | FastAPI, Python 3.11+, uv, Pydantic v2 |
| **에이전트 엔진** | LangGraph StateGraph (7-Node ReAct Pipeline, StreamBridge) |
| **LLM 서빙** | Google Gemini (100% User-Facing & Function Calling) + Local llama.cpp (SLM Preprocessing) |
| **지식 시스템** | OKF (Open Knowledge Format 1.0) + 5-Factor Dynamic Slicer Engine |
| **스토리지 & DB** | File Storage (K3s PVC) + PostgreSQL 16 (SQLAlchemy 2.0 asyncpg, Alembic) |
| **외부 확장** | MCP (JSON-RPC 2.0 HTTP/SSE/stdio), Google Calendar/Gmail API |
| **관측성 & 텔레메트리**| Correlation ID ContextVar, 구조화 JSON 로깅, Langfuse 추적, Liveness/Readiness 프로브 |
| **인프라 & 배포** | K3s (3 Replicas), Traefik Ingress, cert-manager (Let's Encrypt SSL/TLS), Docker |
| **클라이언트** | PWA Web (Responsive Sci-Fi HUD, Web Speech API TTS/STT, WebSocket/SSE) |
