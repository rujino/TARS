# TARS 기술 스택 정의서 (TECH_STACK.md)

TARS 프로젝트의 기술 스택은 **"오브젝트 스토리지 + RDBMS + OKF 표준"**을 융합한 엔터프라이즈 멀티 테넌트 SaaS 프로덕션 표준으로 설계되었습니다.

---

## 1. 지식 &amp; 스토리지 계층 (Knowledge &amp; Storage Trinity) ⭐


| 기술                               | 역할                       | 선정 이유 (Rationale)                                                                                                             |
| :-------------------------------- | :------------------------ | :----------------------------------------------------------------------------------------------------------------------------- |
| **OKF (Open Knowledge Format)**  | **표준화된 지식 규격**           | YAML Frontmatter + Markdown 2계층 구조로 지식 유형, 태그, 관계망을 표준화하여 LLM의 맥락 이해도 극대화                                                     |
| **Object / File Storage**        | **지식 원본 영속 스토리지**        | - 로컬/개발: `/storage/users/{user_id}/wikis/*.md`<br>`- 클라우드/운영: S3/MinIO 호환 오브젝트 스토리지`<br>`➡️ DB 부하 제로, 데이터 영구 보존, Git/옵시디언 호환` |
| **PostgreSQL**                   | **메타데이터 &amp; 인증 RDBMS** | 회원 정보, JWT 인증, 사용자별 파일 경로(`file_path`), 생성/수정일 메타데이터 관리                                                                       |
| **SQLAlchemy 2.0 &amp; Alembic** | 비동기 ORM &amp; 마이그레이션     | 비동기 FastAPI와 완벽히 호환되는 현대적 DB 추상화 및 버전 관리                                                                                      |


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

## 3. 확장형 도구 &amp; MCP 생태계 (Tool &amp; MCP Ecosystem)


| 기술                                 | 역할                   | 선정 이유 (Rationale)                                                     |
| :---------------------------------- | :-------------------- | :--------------------------------------------------------------------- |
| **MCP (Model Context Protocol)**   | **표준 확장 프로토콜 클라이언트** | Anthropic 오픈 표준 MCP Client를 내장하여 외부 MCP 서버(GitHub, DB 등)를 플러그앤플레이로 확장 |
| **Native Tool Registry (`@tool`)** | 내부 커스텀 도구 정의         | TARS 파라미터 조절, 시스템 제어, OKF 파일 탐색 도구 직접 정의                              |
| **External Service Adapters**      | 외부 클라우드 연동           | Google Workspace(Calendar/Gmail) 및 Apple iCloud(캘린더, 미리알림) 연동 어댑터     |


---

## 4. AI &amp; 하이브리드 LLM 엔진 (AI &amp; Serving)


| 기술                             | 역할           | 선정 이유 (Rationale)                                             |
| :------------------------------ | :------------ | :------------------------------------------------------------- |
| **Google Gemini API**          | 클라우드 고지능 LLM | 개발자 크레딧 활용: 고난도 심층 추론, 동적 OKF 지식 융합, 모든 툴 호출(Tool Calling) 전담 |
| **llama.cpp (`llama-server`)** | 온프레미스 로컬 SLM | Windows 로컬 GPU 자원 활용: 빠른 의도 분류, 선행 필터링, 단순 일상 대화 (비용 0원)      |
| **Static Prompt CAG**          | 정적 툴 스키마 캐싱  | TARS 페르소나 및 대형 툴 스키마 JSON만 캐싱하여 75% 비용 절감 및 속도 극대화            |


---

## 5. 관측성, 클라이언트 &amp; 인프라 (Observability, Client &amp; Infra)


| 기술                                         | 역할                  | 선정 이유 (Rationale)                                                                          |
| :------------------------------------------ | :------------------- | :------------------------------------------------------------------------------------------ |
| **Langfuse**                               | LLM 트레이싱 &amp; 모니터링 | 유저별 세션 및 툴 호출 지연 시간, 토큰 소모량 실시간 시각화                                                        |
| **On-Device TTS**                          | 엣지 클라이언트 음성 합성      | - Web: `SpeechSynthesis API`<br>`- iOS: AVSpeechSynthesizer`<br>➡️ 서버 부하 0%, 네트워크 트래픽 초경량화 |
| **Docker &amp; Nginx &amp; Let's Encrypt** | 프로덕션 인프라 &amp; 보안   | 컨테이너화, 정식 HTTPS/WSS 암호화, Rate Limiting                                                     |
| **JWT (JSON Web Token)**                   | 디바이스 인증 &amp; 보안    | 인가된 클라이언트(아이폰)만 백엔드 리소스에 접근하도록 보안 제어                                                       |


