# TARS Frontend Application

Vite + React + TypeScript 기반의 TARS(Tactical Autonomous Robotic System) 차세대 프론트엔드 애플리케이션입니다.  
백엔드 FastAPI의 **전체 23개 엔드포인트(100% 전수 연동)**와 WebSocket 단일 표준 실시간 엔진, 사이드바 대화 세션 타임라인 관리, 미니멀 다크 테마 UI를 제공합니다.

---

## 🏛 계층형 아키텍처 (Layered Architecture)

```
frontend/src/
├── routes/                 # 1. 라우팅 계층 (TanStack Router)
│   ├── paths.ts            #    경로 상수 (HOME: '/', OAUTH_CALLBACK: '/oauth/callback')
│   └── router.tsx          #    Type-safe 라우트 트리 및 GlobalModals 주입
│
├── api/                    # 2. HTTP 통신 계층 (Axios)
│   ├── client.ts           #    Axios 인스턴스 (Bearer 토큰 자동 주입, 401 핸들링)
│   └── endpoints/          #    도메인별 순수 API 호출 함수들 (전체 24개 엔드포인트 100% 매핑)
│       ├── auth.api.ts     #    /api/v1/auth (signup, login, me, ws-ticket)
│       ├── chat.api.ts     #    /api/v1/chat (sessions, messages, delete, ws)
│       ├── persona.api.ts  #    /api/v1/tars/config (get, patch, reset)
│       ├── tools.api.ts    #    /api/v1/tools (servers, toggle, google auth, test)
│       └── system.api.ts   #    /health, /health/liveness, /health/readiness, /metrics
│
├── queries/                # 3. 서버 비동기 상태 계층 (TanStack Query v5)
│   ├── queryClient.ts      #    QueryClient 인스턴스 & 캐시 정책
│   ├── queryKeys.ts        #    계층형 Query Key Factory
│   ├── useAuthQuery.ts     #    인증, 회원가입, 프로필, WebSocket 티켓 훅
│   ├── useChatQuery.ts     #    세션 목록, 메시지 히스토리, 세션 삭제 훅
│   ├── usePersonaQuery.ts  #    TARS 운영 모드 조회, 전환, 기본값 리셋 훅
│   ├── useToolsQuery.ts    #    도구 서버, 스위치 토글, MCP 테스트, Google 연동 훅
│   └── useSystemQuery.ts   #    Liveness, Readiness, Prometheus 메트릭 훅
│
├── websocket/              # 4. 실시간 양방향 통신 계층 (WebSocket Single Standard)
│   ├── client.ts           #    1회용 티켓 인증, 지수 백오프 자동 재연결, Barge-in, 타이핑 전송
│   └── types.ts            #    실시간 이벤트 핸들러 및 프레임 타입
│
├── stores/                 # 5. 클라이언트 전역 상태 계층 (Zustand)
│   ├── useSessionStore.ts  #    현재 활성 session_id, 제목, 사이드바 개폐 상태
│   └── useUIStore.ts       #    모달 (auth, persona, tools, system) 활성 상태
│
├── components/             # 6. UI 컴포넌트 계층 (CSS Modules)
│   ├── layout/
│   │   ├── Header/         #    운영 모드 배지, 시스템 헬스 인디케이터, 도구/인증 버튼
│   │   ├── Sidebar/        #    새 대화 시작, 날짜별(Today/Yesterday 등) 세션 타임라인
│   │   └── Layout.tsx      #    분할 화면 셸 레이아웃
│   ├── chat/
│   │   ├── ChatFeed.tsx    # 베라(Vera)/미우(Miu) 다자간 말풍선, 읽음 확인, 0ms 중단 표시
│   │   ├── TypingIndicator.tsx # 캐릭터 실시간 타이핑 인디케이터
│   │   └── ChatInput.tsx   # 멀티라인 텍스트 입력, 발화 즉시 중단(Barge-in) 버튼
│   └── modals/
│       ├── AuthModal.tsx   # 로그인, 회원가입, 프로필, 1회용 WS 티켓 발급
│       ├── PersonaModal.tsx# Attend(동반자) vs Task(업무) 모드 전환 및 리셋
│       ├── ToolsModal.tsx  # MCP 서버 목록, 도구 토글, 지연시간 테스트, Google 연동
│       └── SystemStatusModal.tsx # K8s 프로브 상태 및 Prometheus 메트릭 모니터링
│
├── pages/                  # 7. 화면/페이지 조립 계층
│   ├── ChatPage/           #    메인 실시간 대화 피드 화면
│   ├── OAuthCallbackPage/  #    Google Workspace OAuth 리다이렉트 콜백 화면
│   └── NotFoundPage/       #    404 에러 화면
│
└── styles/                 # 8. 스타일 시스템 (순수 바닐라 CSS)
    ├── reset.css           #    모던 CSS 리셋
    ├── variables.css       #    미니멀 다크/슬레이트 테마 디자인 토큰
    └── global.css          #    전역 스타일
```

---

## 📊 백엔드 API 연동 전수 조사 결과 (100% 매핑)

| 도메인 | 엔드포인트 | 메서드 | 주요 역할 |
|:---|:---|:---:|:---|
| **Auth** | `/api/v1/auth/signup` | `POST` | 신규 회원가입 및 계정 생성 |
| **Auth** | `/api/v1/auth/login` | `POST` | 로그인 및 JWT 발급 |
| **Auth** | `/api/v1/auth/me` | `GET` | 현재 사용자 프로필 및 계정 상태 |
| **Auth** | `/api/v1/auth/ws-ticket` | `POST` | 30초 단기 1회용 WebSocket 티켓 발급 |
| **Chat** | `/api/v1/chat/sessions` | `GET` | 날짜 그룹 메타데이터 포함 세션 타임라인 |
| **Chat** | `/api/v1/chat/sessions/{session_id}/messages` | `GET` | 세션별 메시지 턴 전체 복원 |
| **Chat** | `/api/v1/chat/sessions/{session_id}` | `DELETE` | 대화 세션 및 메시지 cascade 삭제 |
| **Chat** | `/api/v1/chat/ws` | `WS` | 실시간 토큰 스트리밍, Barge-in, 읽음 확인 |
| **Persona** | `/api/v1/tars/config` | `GET` | TARS 운영 모드 조회 |
| **Persona** | `/api/v1/tars/config` | `PATCH` | Attend / Task 운영 모드 즉시 전환 |
| **Persona** | `/api/v1/tars/config/reset` | `POST` | TARS 설정을 기본값으로 초기화 |
| **Tools** | `/api/v1/tools/servers` | `GET` | 등록된 MCP 및 내장 도구 서버 목록 |
| **Tools** | `/api/v1/tools/{tool_name}/toggle` | `PATCH` | 개별 도구 활성/비활성화 스위칭 |
| **Tools** | `/api/v1/tools/auth/google/url` | `GET` | Google OAuth2 인증 URL 발급 |
| **Tools** | `/api/v1/tools/auth/google/callback` | `GET` | Google OAuth2 인증 콜백 처리 |
| **Tools** | `/api/v1/tools/auth/google/credentials` | `GET` | Google 워크스페이스 연동 상태 확인 |
| **Tools** | `/api/v1/tools/auth/google/credentials` | `POST` | 사용자 정의 Google Client ID/Secret 설정 |
| **Tools** | `/api/v1/tools/auth/google/disconnect` | `POST` | Google 계정 연동 해제 및 토큰 폐기 |
| **Tools** | `/api/v1/tools/servers/{server_id}/test` | `POST` | MCP 서버 핑 및 RTT 지연시간 측정 |
| **System** | `/health` / `/health/liveness` | `GET` | 기본 프로세스 라이브니스 프로브 |
| **System** | `/health/readiness` | `GET` | DB 및 SeaweedFS 스토리지 심층 레디니스 점검 |
| **System** | `/metrics` | `GET` | Prometheus 텔레메트리 메트릭 모니터링 |

---

## 🚀 빠른 시작

```bash
# 1. frontend 디렉토리 이동
cd frontend

# 2. 린트 및 타입 검증
npm run lint
npm run build

# 3. 로컬 개발 서버 구동 (백엔드 프록시 연동)
npm run dev
```
