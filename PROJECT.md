# Project: TARS Phase 2 Full Specification

## Architecture
TARS is structured as a segregated "Trinity Knowledge Layer" + LangGraph hybrid agent state machine + FastAPI real-time token streaming backend + PWA Mobile & Desktop Web Client with On-Device Web Speech TTS:

```
+-------------------------------------------------------------------------------------------------------+
|                                     Client Tier: PWA Web Client                                       |
|   +--------------------------+  +--------------------------+  +-------------------------------------+ |
|   |  TARS Interstellar Theme |  |  JWT Auth & Router State |  |  On-Device Web Speech TTS Engine    | |
|   |  HUD / Monolith UI       |  |  (AuthView <-> ChatView) |  |  (iOS Safari Unlock, Sentence Q) | |
|   +--------------------------+  +--------------------------+  +-------------------------------------+ |
|                                              │                                                        |
|                 ┌────────────────────────────┴────────────────────────────┐                           |
|                 │ WebSocket (/api/v1/chat/ws)  │ SSE (/api/v1/chat/stream) │ (Fallback)               |
|                 ▼                              ▼                          │                           |
+---------------------------------------------------------------------------│---------------------------+
                                                                            │
+---------------------------------------------------------------------------│---------------------------+
|                                        FastAPI Backend                    │                           |
|   +--------------------------+  +--------------------------+  +-----------▼-----+  +----------------+ |
|   |  JWT Auth & Users API    |  |  TARS Persona Settings   |  | SSE / WebSocket |  | Static Files   | |
|   |  (/api/v1/auth)          |  |  (/api/v1/tars/config)   |  | (/api/v1/chat)  |  | (/, /manifest) | |
|   +--------------------------+  +--------------------------+  +-----------------+  +----------------+ |
+----------------------------------------------|--------------------------------------------------------+
                                               │
                                               v
+-------------------------------------------------------------------------------------------------------+
|                                 LangGraph StateGraph Orchestrator                                     |
|  [Dynamic Slicer Context] -> [TARS Persona System Prompt]                                             |
|                                         │                                                             |
|            +----------------------------+----------------------------+                                |
|            v (Internal Tasks Only)                                   v (User Dialogue)                |
|      [llama.cpp Adapter (Local SLM)]                      [Google Gemini Adapter]                     |
|      - Intent classification / Query pre-processing       - User-Facing Response 100%                 |
|      - Entity extraction & internal reasoning only        - High intelligence & tools                 |
+-------------------------------------------------------------------------------------------------------+
                                               │ (User turn completed)
                                               v
+-------------------------------------------------------------------------------------------------------+
|                          Self-Evolving Knowledge Extractor (Background Task)                          |
|          Extracts preferences/rules/facts -> Formats OKF with source: "auto_extracted"                |
+----------------------------------------------|--------------------------------------------------------+
                                               │
                        +----------------------+----------------------+
                        v                                             v
+-------------------------------------------+     +-----------------------------------------------------+
|       Segregated File Storage Layer       |     |          SQLAlchemy 2.0 Async Metadata DB           |
|       /storage/users/{user_id}/wikis/*.md | <-> |          user_wikis index, users, settings          |
|       (Pure Markdown Source of Truth)     |     |          (Fast querying & reconciliation)           |
+-------------------------------------------+     +-----------------------------------------------------+
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | OKF Parser & Serializer | Parse & serialize YAML frontmatter + markdown body conforming to `docs/OKF_SPEC.md` | M1 | R1, docs/OKF_SPEC.md |
| F2 | OKF Pydantic Models & Validator | Validate `okf_version`, `id`, `type`, `title`, `category`, `tags`, `importance`, `source`, `relations` | M1 | R1, docs/OKF_SPEC.md |
| F3 | Multi-Tenant File Storage Manager | User-isolated file operations (`/storage/users/{user_id}/wikis/*.md`), path traversal security, atomic write | M1 | R1, docs/ARCHITECTURE.md |
| F4 | SQLAlchemy 2.0 Async RDBMS Schema | Async models (`User`, `TARSSettings`, `UserWikiIndex`) with SQLite/PostgreSQL compatibility | M1 | R1, docs/TECH_STACK.md |
| F5 | Storage-DB Reconciliation Engine | Bidirectional sync & hash integrity check between markdown files and DB metadata index | M1 | R1, docs/ARCHITECTURE.md |
| F6 | OKF Dynamic Slicer | Multi-factor scoring (importance, tags, relations, context) & token budget dynamic prompt injection | M1 | R1, docs/PRD.md |
| F7 | TARS Persona System Prompt Engine | Dry wit (Humor 90%), extreme honesty (95%), companion/work modes, anti-sycophancy rules | M2 | R2, docs/PRD.md |
| F8 | Hybrid LLM Adapter Interface | Unified `BaseLLMAdapter` with `GeminiAdapter` (User-Facing 100% & Deep Reasoning) and `LlamaCppAdapter` (Lightweight Internal Tasks) | M2 | R2, docs/TECH_STACK.md |
| F9 | Tiered Internal Reasoning & 500ms Fallback | Smart tiered internal routing (SLM for fast pre-processing, Gemini for deep reasoning & user dialogue) with health-probe fallback | M2 | R2, docs/ARCHITECTURE.md |
| F10 | LangGraph StateGraph Pipeline | Complete state machine (`TARSState`, context injection, prompt composition, LLM streaming, memory preservation) | M2 | R2, docs/TECH_STACK.md |
| F11 | Prompt & Static Tool Schema Caching | Static CAG prompt / tool schema caching for cost and latency reduction | M2 | R2, docs/TECH_STACK.md |
| F12 | Self-Evolving Knowledge Extractor Worker | Async background task extracting facts/preferences/rules from conversation turns | M3 | R3, docs/PRD.md |
| F13 | Auto-Extracted OKF Persistence & Sync | Automatic formatting with `source: "auto_extracted"`, atomic `.md` persistence and DB indexing | M3 | R3, docs/OKF_SPEC.md |
| F14 | FastAPI Modular App & Lifespan | App initialization, Lifespan DB engine setup, CORS, global error handling & DI | M4 | R4, docs/TECH_STACK.md |
| F15 | JWT Authentication & User Routes | User signup, login, password hashing (bcrypt), JWT verification, `get_current_user` DI | M4 | R4, docs/PRD.md |
| F16 | TARS Persona Settings REST API | `GET`, `PATCH`, `POST /reset` endpoints for `humor_level`, `honesty_level`, `mode` | M4 | R4, docs/PRD.md |
| F17 | WebSocket Real-Time Token Streaming | `/api/v1/chat/ws` bidirectional token streaming protocol with lifecycle events | M4 | R4, docs/ARCHITECTURE.md |
| F18 | SSE Real-Time Token Streaming | `POST /api/v1/chat/stream` Server-Sent Events token stream endpoint | M4 | R4, docs/TECH_STACK.md |
| F19 | Strict Static Typing Configuration | 100% type annotations with Pydantic v2, TypedDict, Enum, passing `mypy --strict` | M4 | R5, pyproject.toml |
| F20 | Phase 1 E2E Test Suite & Hardening | Full unit, integration, streaming, and adversarial test suite passing 100% | M_Final | Acceptance Criteria |
| F21 | PWA Web Client UI & Interstellar Theme | HUD monolithic dark design, responsive CSS (375px+ / desktop), viewport-fit=cover, standalone UI | M5 | Phase 2 R1, R4 |
| F22 | JWT Auth & Persona Controller UI | Sign up/in/out, token storage, auth route switching, humor/honesty sliders, reset API sync | M5 | Phase 2 R1 |
| F23 | Real-Time Dual Streaming Chat Engine | WebSocket `/api/v1/chat/ws?token=` + SSE fallback, token streaming, markdown & code render | M6 | Phase 2 R2 |
| F24 | On-Device Web Speech API TTS Engine | `window.speechSynthesis`, iOS Safari user gesture unlock, sentence queueing on `[.!?\n]`, TARS tone | M6 | Phase 2 R3 |
| F25 | FastAPI Static Serving & PWA Packaging | `StaticFiles` root mounting, `/manifest.json`, `/sw.js`, iOS PWA meta tags, icons | M7 | Phase 2 R4 |
| F26 | Phase 2 E2E Test Suite & Regression QA | Static serving E2E tests, PWA meta/manifest tests, 100% Phase 1 regression pass, mypy strict | M_Phase2_Final | Phase 2 R5 |
| F27 | Smart Session Manager & Time Decay | 15m 유지, 15m-2h 브릿지 요약, 2h+ 신규 세션 분기 및 OKF 아카이빙 | M8 | Phase 3 R1 |
| F28 | Topic Shift & Natural Language Reset | 대화 주제 급변 감지 및 자연어 리셋 명령 처리 | M8 | Phase 3 R1 |
| F29 | Proactive Greeting Service & API | 접속 시간대/공백/맥락/OKF 기반 위트 있는 능동 오프닝 (`GET /api/v1/chat/greeting`) | M8 | Phase 3 R1 |
| F30 | Tool Schema CAG Manager | 도구 스키마 JSON 및 프롬프트의 정적 캐싱(CAG) 최적화 | M9 | Phase 3 R2 |
| F31 | Async MCP Client & Tool Adapter | 표준 JSON-RPC 2.0 비동기 MCP 클라이언트 및 BaseTool 어댑터 (HTTP, SSE, STDIO, Mock) | M9 | Phase 3 R2 |
| F32 | Google Workspace Adapters & ReAct | Google Calendar, Gmail 도구 어댑터 및 LangGraph ReAct 실행 루프 | M9 | Phase 3 R2 |
| F33 | 5-Factor OKF Dynamic Slicer Engine | Relations, Category, Importance, Recency, Context 기반 5-Factor 가중치 슬라이싱 | M10 | Phase 3 R3 |
| F34 | User-Scoped Tool Hub & API Wiring | `ToolRegistry` 의존성 주입 프로바이더 및 사용자별 토글형 MCP 도구 확장 구조 | M10 | Phase 3 R2, R3 |
| F35 | Phase 3 E2E Test Suite & Victory Audit | 431개 테스트 100% 통과, mypy strict 0 error, ruff 0 warning, VICTORY CONFIRMED | M_Phase3_Final | Phase 3 Final |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | OKF Engine & Segregated Storage | OKF parser/serializer/validator, file storage manager, async DB models & slicer (F1-F6) | none | DONE |
| M2 | LangGraph Orchestrator & TARS Persona | TARS persona prompt, LLM adapters (Gemini/Llama), hybrid router, StateGraph (F7-F11) | M1 | DONE |
| M3 | Self-Evolving Knowledge Extractor | Background knowledge extraction loop, auto-extracted OKF sync (F12-F13) | M1, M2 | DONE |
| M4 | FastAPI Backend & Streaming API | FastAPI setup, JWT auth, TARS config API, WebSocket & SSE streaming, pyproject.toml (F14-F19) | M1, M2, M3 | DONE |
| M_Final | Phase 1 Final Integration | Pass 100% Phase 1 E2E test suite (Tiers 1-4) + Tier 5 Hardening (F20) | M1-M4 | DONE |
| M5 | PWA Client UI, Theme & Persona/Auth | Interstellar HUD theme, responsive CSS, JWT auth view, TARS persona controls, API client (F21, F22) | M4 | DONE |
| M6 | Dual Streaming & On-Device TTS Engines | WebSocket + SSE streaming chat client, markdown renderer, Web Speech API TTS engine with iOS unlock (F23, F24) | M5 | DONE |
| M7 | FastAPI Static Serving & PWA Packaging | FastAPI `StaticFiles` mount, `/manifest.json`, `/sw.js`, PWA icons, iOS meta tags (F25) | M5, M6 | DONE |
| M_Phase2_Final | Phase 2 E2E Tests & QA Verification | `tests/tier3_e2e_api/test_pwa_static_serving.py`, Tiers 1-4 full regression 100% pass, mypy strict & ruff (F26) | M5, M6, M7 | DONE |
| M8 | Smart Session Routing & Proactive Greeting | 시간 감쇄(15m/2h), 브릿지 요약, 주제 전환 및 자연어 리셋, Greeting API (F27-F29) | M_Phase2_Final | DONE |
| M9 | Static Tool CAG & MCP/Google Adapters | ToolCAGManager, AsyncMCPClient, Google Calendar/Gmail 어댑터, ReAct 루프 (F30-F32) | M8 | DONE |
| M10 | 5-Factor OKF Slicing & Tool Wiring | 5-Factor 동적 슬라이서, 자가 진화 루프, ToolRegistry API DI 와이어링 (F33-F34) | M9 | DONE |
| M_Phase3_Final | Phase 3 Full Integration & Victory Audit | 431개 전수 테스트 100% 통과, mypy strict 0 error, ruff clean, VICTORY CONFIRMED (F35) | M8, M9, M10 | DONE |


## Interface Contracts

### 1. PWA Web Client & Auth / Persona API (`tars/static/js/api.js`)
```javascript
class TARSApiClient {
  getToken(): string | null;
  setToken(token: string): void;
  clearToken(): void;
  signup(username, email, password): Promise<{ access_token: string, token_type: string, user: object }>;
  login(username, password): Promise<{ access_token: string, token_type: string, user: object }>;
  getMe(): Promise<object>;
  getConfig(): Promise<{ humor_level: number, honesty_level: number, mode: string }>;
  updateConfig(config: { humor_level?: number, honesty_level?: number, mode?: string }): Promise<object>;
  resetConfig(): Promise<object>;
}
```

### 2. Dual Streaming Client (`tars/static/js/chat.js`)
```javascript
class TARSStreamClient {
  constructor(apiClient: TARSApiClient, callbacks: {
    onStart: (sessionId: string) => void,
    onToken: (chunk: string) => void,
    onEnd: (fullText: string) => void,
    onError: (err: string) => void,
    onStatusChange: (status: string) => void
  });
  connectWebSocket(): void;
  sendMessage(message: string, sessionId?: string): Promise<void>;
  sendSSEMessage(message: string, sessionId?: string): Promise<void>;
}
```

### 3. On-Device Web Speech TTS Engine (`tars/static/js/tts.js`)
```javascript
class TARSTTSEngine {
  constructor();
  setupUnlockListeners(): void; // iOS Safari User Gesture Unlock
  setMute(mute: boolean): void;
  stop(): void;
  pushToken(token: string): void; // Streams & buffers tokens, splits on [.!?\n]
  flush(): void; // Speaks remaining buffered text on stream_end
  enqueue(text: string): void;
  processQueue(): void;
}
```

### 4. FastAPI Static Serving Endpoints (`tars/api/app.py`, `tars/config.py`)
```python
# tars/config.py
class Settings(BaseSettings):
    ...
    static_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "static"
    )

# tars/api/app.py
@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse: ...

@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest() -> FileResponse: ...

@app.get("/sw.js", include_in_schema=False)
async def serve_sw() -> FileResponse: ...

# Mounted after /api/v1 and /health:
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
```

## Code Layout
```
/Users/jinhoryu/Workspace/SideProject/TARS/
├── pyproject.toml
├── README.md
├── docs/
│   ├── OKF_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── PRD.md
│   └── TECH_STACK.md
├── tars/
│   ├── __init__.py
│   ├── config.py                       # Application settings (added static_dir)
│   ├── core/                           # OKF models, parser, validator
│   ├── db/                             # SQLAlchemy 2.0 Async models & session
│   ├── storage/                        # Multi-tenant file storage manager
│   ├── slicer/                         # Dynamic Knowledge Slicer
│   ├── persona/                        # TARS Persona system prompt generator
│   ├── adapters/                       # Gemini & llama.cpp LLM adapters
│   ├── orchestrator/                   # LangGraph StateGraph pipeline
│   ├── extractor/                      # Async Self-Evolving Knowledge Extractor
│   ├── api/                            # FastAPI app, routers, dependencies, streaming
│   │   ├── __init__.py
│   │   ├── app.py                      # FastAPI app (includes static file routes & mount)
│   │   ├── dependencies.py
│   │   ├── routers/
│   │   └── schemas/
│   └── static/                         # [Phase 2] PWA Web Client
│       ├── index.html                  # Single Page Interface (HUD Monolith)
│       ├── manifest.json               # PWA Web App Manifest (Standalone)
│       ├── sw.js                       # Service Worker (App Shell cache + API bypass)
│       ├── css/
│       │   ├── hud.css                 # Interstellar HUD theme & layout
│       │   └── components.css          # Chat, modal, slider, code block styles
│       ├── js/
│       │   ├── app.js                  # Main entry point & SPA router
│       │   ├── api.js                  # REST client (JWT Auth + TARS Persona Config)
│       │   ├── chat.js                 # WebSocket & SSE dual streaming client
│       │   ├── tts.js                  # On-Device Web Speech API engine
│       │   └── vendor/
│       │       ├── marked.min.js       # Offline markdown parser
│       │       └── purify.min.js       # Offline DOMPurify
│       └── icons/
│           ├── icon-192.png
│           ├── icon-512.png
│           └── apple-touch-icon.png
└── tests/
    ├── conftest.py
    ├── tier1_unit/
    ├── tier2_integration/
    ├── tier3_e2e_api/
    │   ├── test_auth_api.py
    │   ├── test_config_api.py
    │   ├── test_websocket_streaming.py
    │   ├── test_sse_streaming.py
    │   └── test_pwa_static_serving.py  # [Phase 2] PWA Static Serving & iOS Meta Tests
    └── tier4_application/
```
