# TARS: 위트 있는 AI 동반자 &amp; 에이전트 (PRD)

## 1. 프로젝트 비전 및 목표

- **비전**: 영화 *인터스텔라*의 TARS처럼, 신뢰할 수 있는 문제 해결 능력과 **유머 지수(90%) / 솔직함(95%)**을 갖춘 나만의 AI 동반자.
- **1차 목표**: 일상적인 대화(Daily Companion Chat)와 클라이언트 디바이스 TTS를 통한 TARS 특유의 음성 피드백 제공.
- **확장 목표**: **오브젝트 스토리지 + DB + OKF 삼위일체 지식 베이스, 자가 진화 루프, MCP/외부 도구 연동**을 통한 실생활 보조.
- **엔지니어링 목표**: **분리형 스토리지(File + RDBMS) + OKF 표준 엔진 + LangGraph A2A + Langfuse LLMOps**, 그리고 프로덕션 표준(Nginx, SSL, Docker) 아키텍처 구축.

---

## 2. 노드 및 하드웨어 구성

1. **Windows Desktop (Main Server)**:
  - **FastAPI + LangGraph + Storage/DB + OKF Engine**:
    - **Storage Layer**: 사용자별 OKF 마크다운 문서 원본 저장 (`/storage/users/{user_id}/wikis/*.md`).
    - **DB Layer**: 회원 정보, TARS 파라미터, 파일 경로(`file_path`) 메타데이터 관리.
    - **OKF Engine**: 문서 헤더 파싱 ➔ 지식 지도 구성 ➔ 동적 슬라이싱 주입.
    - **정적 툴 CAG**: 시스템 지시문 및 대형 툴 스키마 JSON 캐싱.
    - **비동기 지식 추출기**: 대화 속 중요 정보 감지 ➔ 새 OKF 파일 자동 생성 ➔ 스토리지/DB 자동 저장.
  - **Langfuse Tracing Layer**: 유저 세션별 대화 및 툴 호출 과정 트레이싱.
  - Nginx 리버스 프록시 + Let's Encrypt SSL/TLS 종단.
2. **Mac (Development Environment)**:
  - Python `uv` 패키지 관리자를 활용한 주 개발 환경.
3. **iPhone (Edge Client)**:
  - JWT 인증 기반으로 서버에 접속하여 텍스트 대화 송수신.
  - 수신된 텍스트를 **아이폰 내장 TTS 엔진(AVSpeechSynthesizer)**으로 TARS 톤(피치/속도 조정)에 맞춰 실시간 음성 출력.

---

## 3. 핵심 기능 요구사항 (Key Requirements)

### 3.1. 오브젝트 스토리지 + DB + OKF 지식 아키텍처

- **지식 원본 영속화**: 순수 OKF 포맷(`.md`)으로 파일시스템/오브젝트 스토리지에 보관 (데이터 영구 보존, Git 호환).
- **초경량 메타데이터 DB**: RDBMS는 `user_id`, `okf_id`, `file_path`, `updated_at` 메타데이터만 초고속 관리.
- **OKF 전용 엔진**: Frontmatter 메타데이터 파싱 및 지식 관계망(`relations`) 기반 동적 슬라이싱 주입.

### 3.2. 대화 기반 자가 학습 OKF 지식 베이스

- **대화 속 자동 지식 포착**: 사용자가 대화 중에 언급한 새로운 선호도, 규칙, 일정 정보를 TARS가 자동 추출.
- **OKF 파일 자동 생성**: `source: "auto_extracted"` 태그와 함께 YAML Frontmatter + Markdown 구조로 파일 생성.
- **비동기 백그라운드 처리**: 대화 응답 속도에 영향을 주지 않도록 비동기 백그라운드 태스크로 스토리지/DB에 저장.

### 3.3. 데이터베이스 &amp; 회원 관리 (RDBMS &amp; Auth)

- **회원가입 / 로그인**: Passlib(bcrypt) 비밀번호 해싱 및 JWT 액세스 토큰 발급.
- **개인화 설정 저장**: 유저별 선호 `humor_level`, `honesty_level`, TARS 모드 저장.
- **대화 이력 보존**: 세션별 대화 메시지 DB 저장 및 이전 대화 불러오기 지원.

### 3.4. LangGraph & 도구 생태계 (LangGraph & Tools)

- **A2A 계층형 오케스트레이션**:
  - **사용자 대화 응답 (100%)**: Google Gemini 전담 (TARS 고유 페르소나 및 지식 융합 발화).
  - **경량 내부 추론**: 로컬 SLM(llama.cpp) 전담 (빠른 의도 분류, 단순 쿼리 전처리, 키워드 추출).
  - **심층 내부 추론**: Google Gemini 전담 (다단계 계획, 복잡한 지식 자가 추출 및 충돌 해결, 툴 파싱).
  - **무중단 회로 차단기 (Circuit Breaker)**: 로컬 SLM 장애/지연 시 경량 내부 작업도 Gemini로 즉시 Fallback.
- **정적 툴 CAG**: 대형 툴 JSON 스키마만 캐싱하여 75% 비용 절감 및 속도 극대화.
- **확장형 도구 & MCP 생태계**:
  - MCP(Model Context Protocol) 클라이언트(HTTP/SSE/stdio/Mock), Google Calendar/Gmail 어댑터 내장.
  - **사용자별 토글형 원클릭 플러그인 허브 (User-Scoped Toggleable Tool Hub)**:
    - 앱/웹 UI에서 사용자가 구글 캘린더, 지메일, 공용 날씨/뉴스 MCP, 사설 MCP 서버 등을 스위치 토글(ON/OFF)로 간편하게 활성화/비활성화.
    - 내부 전송 방식(stdio 서브프로세스, 원격 HTTP/SSE, OAuth2 토큰 주입 등)을 사용자에게 완벽히 은닉화(캡슐화)하여 직관적인 UX 제공.
    - 사용자 계정별로 활성화된 도구들만 동적으로 선별하여 세션별 `ToolRegistry`에 자동 주입.

### 3.5. 온디바이스 음성 & 보안 인프라

- **On-Device TTS**: 텍스트만 전송하여 아이폰 내장 엔진으로 즉시 발화 (서버 부하 0%).
- **정공법 보안**: Nginx + Let's Encrypt 정식 SSL/TLS (HTTPS/WSS), Docker Compose 배포.

### 3.6. 음성 우선(Voice-First) 능동 대화 & 스마트 세션 관리

- **앱 실행 시 선제 화제 제시 (App-Launch Proactive Greeting)**:
  - 앱 실행(Foreground 진입) 시 빈 입력창 대기 대신, TARS가 접속 시간대/공백 시간(Idle)/이전 대화 맥락/OKF 지식 기반으로 1~2문장의 위트 있는 오프닝 멘트를 먼저 음성으로 발화하고 마이크(STT)를 자동 활성화.
- **상황별 스마트 세션 분기 (Smart Session Routing)**:
  - **시간 경과 기반 감쇄(Time Decay)**: 단기(15분 이내, 세션 유지) / 중기(15분~2시간, 브릿지 요약 후 분기) / 장기(2시간 이상, 완전 새 세션).
  - **의미론적 주제 전환(Topic Shift)**: 로컬 SLM이 주제 급변 감지 시 이전 세션을 아카이브하고 깨끗한 새 세션/태스크 스레드로 분기.
  - **음성 명령어 제어**: "TARS, 리셋해", "새로운 주제야" 등의 자연어 음성 명령으로 세션 초기화 지원.
- **세션-지식 분리 구조**:
  - 세션은 단기 작업 기억(Working Memory)으로 기민하게 초기화/분기되며, 세션 종료/분기 시 이전 대화는 비동기 지식 추출기를 통해 OKF(장기 기억)로 영구 보존.

---

## 4. 단계별 마일스톤 (Milestones)

- **Phase 1: Mac 개발 환경 세팅 & DB/Storage + OKF Engine + LangGraph Core 프로토타입 [DONE]**
  - `uv` 기반 FastAPI + SQLAlchemy(SQLite) + File Storage + OKF Engine + LangGraph 뼈대 구성.
  - User 스키마, `user_wikis` 메타데이터 스키마 모델링 및 JWT 인증.
  - 로컬 `llama.cpp` (내부 경량 추론 노드) + Google Gemini (사용자 응답 생성 노드) 연결 및 TARS 시스템 프롬프트(Humor 90%) 주입.
- **Phase 2: 비동기 텍스트 스트리밍 & On-Device TTS 웹 클라이언트(PWA) [DONE]**
  - WebSocket/SSE 실시간 토큰 스트리밍.
  - 아이폰 브라우저에서 로그인 후 대화 텍스트 수신 즉시 Web Speech API로 TARS 톤 음성 발화 구현.
- **Phase 3: OKF 동적 슬라이싱 & 정적 CAG 툴 연동 & 비동기 지식 자가 진화 & 스마트 세션 라우팅 [DONE]**
  - 5-Factor 점수화 기반 OKF 지식 동적 슬라이싱 및 대화 기반 OKF 파일 자동 생성 비동기 자가 진화 루프.
  - 정적 툴 스키마 CAG 적용 및 MCP(HTTP/SSE/stdio) / Google 도구 어댑터 & ToolRegistry API 와이어링.
  - 앱 실행 시 능동 오프닝(Proactive Greeting) 엔드포인트 및 시간/주제 기반 스마트 세션 라우팅 엔진 구축.
- **Phase 4: 프로덕션 정공법 인프라 & 컨테이너화 [DONE]**
  - Docker Compose 패키징 (FastAPI + PostgreSQL + Nginx + Certbot).
  - 도메인 연동 및 SSL/TLS 보안 인증서 적용.
- **Phase 5: 네이티브 iOS 앱 확장 및 포트폴리오 문서화**
  - SwiftUI 기반 전용 TARS 앱 빌드 & `AVSpeechSynthesizer` 네이티브 TTS / STT 연동.
  - 앱 실행 즉시 TARS 오프닝 음성 출력 ➔ 마이크 자동 리스닝 Voice-First 턴테이킹 UX 구현.
  - 아키텍처 다이어그램 및 엔지니어링 문서(README/블로그) 정리.
