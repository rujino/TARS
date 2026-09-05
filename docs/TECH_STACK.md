# TARS 기술 스택 정의서 (TECH_STACK.md)

TARS 프로젝트의 기술 스택은 **"오브젝트 스토리지 + RDBMS + OKF 표준"**을 융합하고 **LangGraph ReAct 에이전트 및 K3s 엣지 오케스트레이션**을 기반으로 하는 프로덕션 사양으로 구축되었습니다.

---

## 1. 지식 & 스토리지 계층 (Knowledge & Storage Trinity)

| 기술 | 역할 | 구현 및 선정 이유 (Rationale) |
| :--- | :--- | :--- |
| **OKF (Open Knowledge Format 1.0)** | **표준화된 지식 규격** | YAML Frontmatter + Markdown 본문의 2계층 구조로 지식 유형(`type`), 중요도(`importance`), 출처(`source`), 관계망(`relations`)을 표준화하여 LLM 맥락 이해도 극대화 |
| **Object / File Storage** | **지식 원본 영속 스토리지** | K3s `local-path` PVC 기반 영구 보존 (`/storage/users/{user_id}/wikis/*.md`)<br>➡️ DB I/O 부하 제로, 데이터 영구 보존 및 완벽한 Git 호환성 확보 |
| **PostgreSQL 16** | **메타데이터 & 인증 RDBMS** | 회원 정보, JWT 인증, 사용자별 파일 경로(`file_path`), 생성/수정일, 대화 세션 및 턴 이력 관리 |
| **SQLAlchemy 2.0 & Alembic** | **비동기 ORM & 마이그레이션** | 비동기 FastAPI와 완벽히 호환되는 현대적 DB 추상화 (`asyncpg` 드라이버, 커넥션 풀 튜닝: `pool_size=20, max_overflow=10, pool_recycle=1800, pool_pre_ping=True`) 및 비동기 스키마 버전 관리 (`0001_initial_schema.py`). 컨테이너 기동 시 자동 마이그레이션 부트스트랩 |
---

## 2. 백엔드 & 에이전트 오케스트레이션 (Backend & Agent Framework)

| 기술 | 역할 | 구현 및 선정 이유 (Rationale) |
| :--- | :--- | :--- |
| **Python 3.11+** | 주 개발 언어 | 비동기 태스크 최적화, 엄격한 정적 타입 힌팅 (`mypy`), 최신 AI SDK 호환 |
| **uv** | 초고속 패키지 관리자 | 결정론적 락파일(`uv.lock`) 및 멀티스테이지 컨테이너 빌드 캐시 가속화 |
| **FastAPI** | 백엔드 웹 서버 | 비동기(Asyncio) 네이티브 지원, Pydantic v2 기반 고성능 데이터 검증, OpenAPI 자동 문서화, `lifespan` 기반 Graceful Shutdown 관리 |
| **LangGraph (0.2+)** | **에이전트 상태 머신 & ReAct 오케스트레이션** | 7개 노드 파이프라인(`session_node` ➔ `reset_node` / `slicer_node` ➔ `prompt_node` ➔ `llm_node` ⇄ `tool_node` ➔ `postprocess_node`)으로 복잡한 에이전트 제어 흐름 단일화. State 격리 및 조건부 라우팅 전담 |
| **LangGraphStreamBridge** | 실시간 스트리밍 브릿지 | LangGraph의 `astream_events(v2)`를 소비하여 `AgentStreamEvent` 포맷(`stream_start`, `token`, `tool_start`, `tool_result`, `stream_end`, `done`)으로 변환 및 WebSocket/SSE 실시간 중계 |
| **Pydantic v2 & PyYAML** | 데이터 유효성 검증 & OKF 파서 | OKF 메타데이터 검증, 스키마 직렬화/역직렬화 및 런타임 유효성 보장 |

---

## 3. 확장형 도구 & MCP 생태계 (Tool & MCP Ecosystem)

| 기술 | 역할 | 구현 및 선정 이유 (Rationale) |
| :--- | :--- | :--- |
| **MCP (Model Context Protocol)** | **표준 확장 프로토콜 클라이언트** | Anthropic 오픈 표준 JSON-RPC 2.0 MCP Client 내장 (HTTP, SSE, stdio, Mock 트랜스포트 지원). 도구 실행별 10초 타임아웃 격리 및 세션 관리 |
| **Native Tool Registry (`BaseTool`)** | 통합 도구 레지스트리 | 사용자 계정별로 활성화된 도구들만 동적으로 선별하여 세션별 주입. Gemini Function Calling 스키마 자동 변환 및 호출 파싱 |
| **External Service Adapters** | 외부 클라우드 연동 어댑터 | Google Workspace (Google Calendar, Gmail API) 네이티브 어댑터 내장 |
| **Prompt CAG (Cache Augmented Gen)** | 정적 스키마 캐싱 | TARS 페르소나 및 대형 툴 스키마 JSON을 인메모리 캐싱하여 75% 토큰 절감 및 응답 지연 최소화 |

---

## 4. AI & 하이브리드 LLM 엔진 (AI & Serving)

| 기술 | 역할 | 구현 및 선정 이유 (Rationale) |
| :--- | :--- | :--- |
| **Google Gemini API** | 클라우드 고지능 LLM | - **사용자 대화 응답(User-Facing Response) 100% 전담** (TARS 고유 위트 페르소나 및 지식 융합 발화)<br>- **Gemini Function Calling**: 도구 호출 인자 정밀 생성 및 도구 반환값 종합 발화 |
| **llama.cpp (`llama-server`)** | 온프레미스 로컬 SLM | - **경량 내부 추론 전담** (사용자 대화 직접 생성 배제, 빠른 의도 분류/전처리/키워드 추출)<br>- **C++/GGUF 경량 런타임**: VRAM 선점 없이 CPU/GPU 자원 효율 극대화<br>- **OpenAI 호환 API 규격 (`LlamaCppAdapter`)**: 표준 엔드포인트 연동 및 유연성 확보 |
| **Hybrid LLM Router** | 양방향 서킷 브레이커 | 로컬 SLM 지연/장애 시 Gemini로 즉시 Fallback하며, 클라우드 장애 발생 시에도 우아한 에러 핸들링을 보장하는 회로 차단기 탑재 |

---

## 5. 관측성, 보안 & 인프라 (Observability, Security & Infra)

| 기술 | 역할 | 구현 및 선정 이유 (Rationale) |
| :--- | :--- | :--- |
| **Telemetry & Correlation ID** | 분산 추적 & 구조화 로깅 | `tars.core.telemetry` 모듈 기반 Request Correlation ID(`ContextVar`) 전파, JSON 구조화 로깅 포맷터, 성능 메트릭 기록 |
| **Health Probes** | 상태 진단 엔드포인트 | K3s 파드 생존 확인용 `/health/live` 및 DB/스토리지/외부 연결성을 검증하는 `/health/ready` 분리 운영 |
| **Langfuse** | LLM 트레이싱 & 모니터링 | 세션 및 턴 단위 지연 시간, 토큰 소모량, 도구 호출 추적 |
| **비동기 보안 & Auth** | 인증 & 암호화 | `asyncio.to_thread` non-blocking bcrypt 해싱, JWT 액세스 토큰, 엄격한 CORS Origin 화이트리스트, 프롬프트 인젝션 방어 태그 격리 |
| **K3s (Lightweight Kubernetes)** | 선언적 컨테이너 오케스트레이션 | 단일 노드/홈서버 환경에서 마스터 메모리 1GB 미만으로 운영되는 경량 k8s. 3-Replica 무중단 롤링 배포 및 PVC 영구 볼륨 데이터 영속화 |
| **Traefik & cert-manager** | Ingress & SSL/TLS 자동화 | Let's Encrypt 자동 발급/갱신 기반 HTTPS/WSS 종단 및 무지연 스트리밍 프록시 |
| **On-Device Web Speech TTS/STT**| 클라이언트 음성 입출력 | 브라우저 내장 `SpeechSynthesis` 및 `SpeechRecognition` API를 활용하여 서버 GPU 부하 0% 및 TARS 음성 인터랙션 제공 |


