# Project: TARS Phase 3

## Architecture
TARS Phase 3는 세션 생명주기 관리(Working Memory), 정적 툴 CAG 및 외부 도구(MCP/Google Workspace) 연동, 그리고 OKF 동적 지식 슬라이싱 및 비동기 자가 진화 루프를 통합하여 완성된 지능형 AI 에이전트를 구축합니다.

### 1. Data & Control Flow
```
[User Request / Client]
       │
       ▼
[FastAPI: /api/v1/chat/ws, /stream, /greeting]
       │
       ├─► [SmartSessionManager]: Time Decay (15m/2h) & Topic Shift & Reset
       │         │
       │         └─► (세션 종료/분기 시) ──► [Background: OKF Extractor] ──► [FileStorage & UserWikiIndex DB]
       │
       ├─► [DynamicSlicerEngine]: 5-Factor 점수화(Context, Importance, Type, Relations, Recency) & DB Fast Pre-filtering
       │         │
       │         └─► Dynamic Knowledge Slice ──┐
       │                                        ▼
       └─► [LangGraph StateGraph Engine] ◄── [ToolCAGManager (Static System Prompt + Tool JSON Schemas)]
                 │
                 ├─► [llm_node]: Function Calling / Tool Selection
                 │         │
                 │         ▼ (tool_calls 감지 시)
                 ├─► [tool_node]: ToolRegistry (MCP Client & Google Workspace Adapters)
                 │         │
                 │         └─► (Graceful Fallback on error) ──► ReAct Loop re-entry
                 │
                 └─► Token Streaming & Final Response
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | ChatSession & ChatMessage DB Models | 세션 및 메시지 이력 영속화 ORM 모델 | M1 | Survey 1 (R1) |
| 2 | Time Decay Session Routing | 15분 이내(유지), 15분~2시간(Bridge Summary+분기), 2시간 초과(신규 세션) | M1 | Survey 1 (R1) |
| 3 | Topic Shift & Natural Reset | 자연어 리셋 명령 처리 및 SLM 기반 주제 급변 감지/세션 분기 | M1 | Survey 1 (R1) |
| 4 | Proactive Greeting Endpoint | GET /api/v1/chat/greeting (시간대, 유휴시간, 맥락, OKF 5-Factor 오프닝) | M1 | Survey 1 (R1) |
| 5 | Tool Base & Registry | BaseTool 추상화, ToolParameter, ToolRegistry 구현 | M2 | Survey 2 (R2) |
| 6 | Static Tool CAG Manager | 정적 시스템 지침 + 대형 도구 스키마 번들링 및 Gemini/In-Memory 캐싱 | M2 | Survey 2 (R2) |
| 7 | MCP Client & Tool Adapter | 표준 JSON-RPC 2.0 비동기 MCP 클라이언트 및 어댑터 | M2 | Survey 2 (R2) |
| 8 | Google Workspace Adapters | Google Calendar (3종) 및 Gmail (3종) 도구 어댑터 & Mock 모드 | M2 | Survey 2 (R2) |
| 9 | LangGraph ReAct Loop & Graceful Fallback | TARSState 확장, tool_node 격리 실행, 에러 시 Fallback, should_continue 라우터 | M2 | Survey 2 (R2) |
| 10 | 5-Factor Dynamic OKF Slicing | Context, Importance, Type, Relations, Recency 다중 팩터 점수화 & 토큰 예산 관리 | M3 | Survey 3 (R3) |
| 11 | DB Index Fast Pre-filtering | UserWikiIndex 기반 1차 메타데이터 필터링 및 스토리지 I/O 최적화 | M3 | Survey 3 (R3) |
| 12 | Background Knowledge Self-Evolution | 대화 턴/세션 종료 시 비동기 OKF Extractor 트리거 & DB 원자적 동기화 | M3 | Survey 3 (R3) |
| 13 | Real-time Knowledge Feedback Loop | 추출된 OKF가 다음 대화 및 Proactive Greeting에 실시간 인출되는 루프 완결 | M3 | Survey 3 (R3) |
| 14 | Comprehensive E2E & Static Analysis | Tier 1~4 테스트 100% 통과, mypy --strict, ruff check 무결성 달성 | M4 | Survey 1,2,3 (R1-R3) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | 스마트 세션 라우팅 & 능동 오프닝 | DB 세션/메시지 모델, Time Decay, Topic Shift, Reset, Proactive Greeting | none | DONE |
| M2 | 정적 툴 CAG & 외부 도구(MCP/Google) 연동 | ToolRegistry, ToolCAGManager, MCP Client, Google Workspace Adapters, LangGraph ReAct | none | DONE |
| M3 | OKF 동적 슬라이싱 & 자가 진화 루프 | 5-Factor 슬라이서, DB 사전필터링, API 백그라운드 지식 추출기 연동, 실시간 반영 | M1, M2 | DONE |
| M4 | E2E 테스트 스위트 및 종합 검증 | 전체 단위/통합/E2E 테스트 100% 통과, mypy --strict, ruff check 무결성 | M1, M2, M3 | DONE |

## Interface Contracts

### 1. SmartSessionManager ↔ ChatRouter & GreetingService
```python
class SmartSessionManager:
    async def get_or_create_session(
        self,
        db: AsyncSession,
        user_id: str,
        requested_session_id: str | None = None,
        incoming_message: str | None = None,
    ) -> tuple[ChatSession, list[ChatMessage], str | None]: ...

    async def record_turn(
        self,
        db: AsyncSession,
        session_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None: ...
```

### 2. ToolCAGManager & ToolRegistry ↔ LangGraph StateGraph
```python
class ToolRegistry:
    def register_tool(self, tool: BaseTool) -> None: ...
    def get_all_tool_definitions(self) -> list[dict[str, Any]]: ...
    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...

class ToolCAGManager:
    def get_cached_system_prompt_and_tools(
        self, base_prompt: str, tools: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]: ...
```

### 3. DynamicSlicerEngine & SelfEvolvingKnowledgeWorker ↔ Storage & API
```python
class DynamicSlicerEngine:
    async def slice_context(
        self,
        user_id: str,
        query: str,
        context_messages: list[str] | None = None,
        token_budget: int = 1500,
        profile: str = "chat",
        db: AsyncSession | None = None,
    ) -> SlicedKnowledgeResult: ...

class SelfEvolvingKnowledgeWorker:
    async def extract_and_sync(
        self,
        user_id: str,
        conversation_turns: list[dict[str, str]],
        db: AsyncSession | None = None,
    ) -> list[str]: ...
```

## Code Layout
- `tars/db/models.py`: `ChatSession`, `ChatMessage` ORM 모델 추가 (M1 - DONE)
- `tars/core/session/`: `manager.py`, `detector.py` (M1 - DONE)
- `tars/services/greeting.py`: `ProactiveGreetingService` (M1 - DONE)
- `tars/tools/`: `base.py`, `registry.py`, `cag.py`, `mcp/`, `google/` (M2 - DONE)
- `tars/orchestrator/`: `state.py`, `nodes.py`, `graph.py` (M2 - DONE)
- `tars/slicer/`: `engine.py`, `models.py` (M3 - DONE)
- `tars/extractor/`: `worker.py`, `prompts.py` (M3 - DONE)
- `tars/api/routers/chat.py`: 세션 바인딩, 백그라운드 태스크 연동, Greeting 엔드포인트 (M1, M3 - DONE)
- `tars/config.py`: 설정 확장 (M2, M3 - DONE)
- `tests/`: 단위/통합/E2E 테스트 스위트 (M1, M2, M3, M4 - DONE, 431 passed)
