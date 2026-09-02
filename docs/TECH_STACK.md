# TARS 기술 스택 정의서 (TECH_STACK.md)

TARS 프로젝트의 기술 스택은 **"오브젝트 스토리지 + RDBMS + OKF 표준"**을 융합한 엔터프라이즈 멀티 테넌트 SaaS 프로덕션 표준으로 설계되었습니다.

---

## 1. 지식 &amp; 스토리지 계층 (Knowledge &amp; Storage Trinity) ⭐


| 기술                               | 역할                       | 선정 이유 (Rationale)                                                                                                             |
| :-------------------------------- | :------------------------ | :----------------------------------------------------------------------------------------------------------------------------- |
| **OKF (Open Knowledge Format)**  | **표준화된 지식 규격**           | YAML Frontmatter + Markdown 2계층 구조로 지식 유형, 태그, 관계망을 표준화하여 LLM의 맥락 이해도 극대화                                                     |
| **Object / File Storage**        | **지식 원본 영속 스토리지**        | - 로컬/개발: `/storage/users/{user_id}/wikis/*.md`<br>`- 클라우드/운영: S3/MinIO 호환 오브젝트 스토리지`<br>`➡️ DB 부하 제로, 데이터 영구 보존, Git/옵시디언 호환` |
| **PostgreSQL**                   | **메타데이터 &amp; 인증 RDBMS** | 회원 정보, JWT 인증, 사용자별 파일 경로(`file_path`), 생성/수정일 메타데이터 관리                                                                       |
| **SQLAlchemy 2.0 & Alembic** | 비동기 ORM & 마이그레이션 | 비동기 FastAPI와 완벽히 호환되는 현대적 DB 추상화 및 비동기 스키마 버전 관리 (`asyncpg` + `Alembic`). 컨테이너 부팅 시 자동 마이그레이션 실행 및 스키마 드리프트 방지 (`0001_initial_schema.py`) |
---

## 2. 백엔드 &amp; 에이전트 오케스트레이션 (Backend &amp; Agent Framework)


| 기술                           | 역할                               | 선정 이유 (Rationale)                                                                      |
| :---------------------------- | :-------------------------------- | :-------------------------------------------------------------------------------------- |
| **Python 3.11+**             | 주 개발 언어                          | AI 생태계 호환성 및 풍부한 라이브러리 지원                                                              |
| **uv**                       | 패키지 및 가상환경 관리                    | 기존 `pip`/`poetry` 대비 10~100배 빠른 빌드 속도 및 결정론적 의존성 관리                                    |
| **FastAPI**                  | 백엔드 웹 서버                         | 비동기(Asyncio) 네이티브 지원, Pydantic v2 기반 고성능 데이터 검증, OpenAPI 자동 문서화                        |
| **LangGraph**                | **에이전트 상태 머신 &amp; A2A 오케스트레이션** | **과도한 추상화를 배제하고 로컬 SLM과 Gemini 간의 A2A 협업 그래프를 세부적으로 직접 제어**. 유저별 State 격리 및 조건부 분기 핸들링 |
| **WebSockets / SSE**         | 실시간 통신 프로토콜                      | LangGraph의 `astream()` 비동기 이벤트를 클라이언트에 실시간 저지연 스트리밍                                    |
| **Pydantic v2 &amp; PyYAML** | 데이터 유효성 검증 &amp; OKF 파서          | OKF 메타데이터 검증 및 스키마 파싱                                                                  |


---

## 3. 확장형 도구 & MCP 생태계 (Tool & MCP Ecosystem)


| 기술                                 | 역할                   | 선정 이유 (Rationale)                                                     |
| :---------------------------------- | :-------------------- | :--------------------------------------------------------------------- |
| **MCP (Model Context Protocol)**   | **표준 확장 프로토콜 클라이언트** | Anthropic 오픈 표준 JSON-RPC 2.0 MCP Client 내장 (HTTP, SSE, STDIO, Mock 멀티 트랜스포트 지원) |
| **Native Tool Registry (`BaseTool`)** | 통합 도구 레지스트리         | TARS 파라미터 조절, 시스템 제어, OKF 파일 탐색 및 MCP/Google 도구 통합 관리 및 Gemini 스키마 자동 변환 |
| **External Service Adapters**      | 외부 클라우드 연동           | Google Workspace(Calendar/Gmail) 및 Apple iCloud(캘린더, 미리알림) 연동 어댑터     |
| **Toggleable Plugin Hub**          | **원클릭 사용자 도구 관리**   | 사용자가 stdio/HTTP/토큰 등 기술 디테일을 몰라도 UI에서 토글(ON/OFF)로 도구를 추가하는 추상화 계층 |


---

## 4. AI &amp; 하이브리드 LLM 엔진 (AI &amp; Serving)


| 기술                             | 역할           | 선정 이유 (Rationale)                                             |
| :------------------------------ | :------------ | :------------------------------------------------------------- |
| **Google Gemini API**          | 클라우드 고지능 LLM | - **사용자 대화 응답(User-Facing Response) 100% 전담** (TARS 고유 페르소나 및 지식 융합)<br>- **복잡한 심층 내부 추론 전담** (다단계 계획, 복잡한 지식 자가 추출 및 충돌 해결, 툴 인자 파싱 및 결과 합성) |
| **llama.cpp (`llama-server`)** | 온프레미스 로컬 SLM | - **경량 내부 추론 전담** (사용자 대화 직접 생성 배제, 빠른 의도 분류/전처리/키워드 추출)<br>- **리소스 오버헤드 최소화**: C++ 기반 경량 런타임 및 GGUF 포맷을 활용하여 VRAM 선점(Pre-allocation) 없이 단일 머신 환경에서 CPU/GPU 자원 효율 극대화<br>- **표준 인터페이스**: OpenAI 호환 API 규격(`LlamaCppAdapter`)을 준수하여 향후 고처리량 배치 환경(vLLM 등)으로의 전환 유연성 확보 |
| **Static Prompt CAG**          | 정적 툴 스키마 캐싱  | TARS 페르소나 및 대형 툴 스키마 JSON만 캐싱하여 75% 비용 절감 및 속도 극대화            |


---

## 5. 관측성, 클라이언트 &amp; 인프라 (Observability, Client &amp; Infra)


| 기술                                         | 역할                  | 선정 이유 (Rationale)                                                                          |
| :------------------------------------------ | :------------------- | :------------------------------------------------------------------------------------------ |
| **Langfuse**                               | LLM 트레이싱 &amp; 모니터링 | 유저별 세션 및 툴 호출 지연 시간, 토큰 소모량 실시간 시각화                                                        |
| **On-Device TTS**                          | 엣지 클라이언트 음성 합성      | - Web: `SpeechSynthesis API`<br>`- iOS: AVSpeechSynthesizer`<br>➡️ 서버 부하 0%, 네트워크 트래픽 초경량화 |
| **K3s (Lightweight Kubernetes)**           | 컨테이너 오케스트레이션     | - **단일 노드/홈서버 최적화**: 표준 k8s API 및 선언적 매니페스트(Deployment, Service, PVC, Secret)를 유지하면서도 마스터 노드 메모리 사용량을 1GB 미만으로 경량화<br>- **고가용성 & 자가 복구**: 컨테이너 비정상 종료 시 자동 재시작 및 롤링 업데이트 제공 |
| **Traefik &amp; cert-manager**             | Ingress &amp; SSL/TLS 자동화 | K3s 기본 내장 Traefik과 Let's Encrypt 자동 발급기(cert-manager)를 연동하여 HTTPS/WSS 엔드포인트 자동 암호화 및 갱신 |
| **Docker**                                 | 로컬 개발 및 컨테이너 빌드   | 다단계 빌드(Multi-stage build) 및 `uv` 캐시 마운트를 통한 초경량 런타임 이미지 패키징 및 K3s containerd 엔진 임포트 |
| **JWT (JSON Web Token)**                   | 디바이스 인증 &amp; 보안    | 인가된 클라이언트(아이폰)만 백엔드 리소스에 접근하도록 보안 제어                                                       |


