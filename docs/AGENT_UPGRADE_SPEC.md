# TARS Agent Functionality Upgrade & Architecture Specification
> **문서 상태**: Draft / Engineering Blueprint  
> **대상 모듈**: `tars.orchestrator`, `tars.adapters`, `tars.tools`, `tars.api.routers.chat`, `tars.slicer`, `tars.extractor`  
> **최초 작성일**: 2026-09-03  
> **목적**: 클라이언트(iOS/Web) 인터페이스 연결 전, TARS의 실제 에이전트 지능, ReAct 도구 호출, 실시간 스트리밍 프로토콜 및 자가 진화 파이프라인의 완성도를 고도화하기 위한 상세 분석 및 기술 구현 명세서.

---

## 1. 개요 및 목적 (Overview & Goals)

TARS 프로젝트는 영화 *인터스텔라*의 AI 로봇 TARS처럼, **위트 있는 페르소나(유머 90%, 정직 95%)**를 유지하면서 실제 사용자의 문제(일정, 이메일, 문서 지식, 외부 도구 연동)를 지능적으로 해결하는 개인용 AI 동반자를 목표로 한다.

현재 코드베이스는 5-Factor 지식 슬라이서, 페르소나 프롬프트 생성기, 스마트 세션 매니저, 비동기 지식 자가 진화 루프, 쿠버네티스(K3s) 프로덕션 배포 스택까지 탄탄한 아키텍처를 갖추고 있다.

그러나 **실제 클라이언트와 소통하는 서빙 API(`chat.py`)와 LangGraph ReAct 에이전트 엔진 간의 연계가 미완성**되어 있으며, **LLM 어댑터 레벨에서 실제 Function Calling(도구 호출) 처리가 누락**되어 있어 실제 도구 체이닝이 발화 중에 동작하지 못하는 병목이 존재한다.

본 문서는 이러한 병목 지점들을 정밀 분석하고, 에이전트가 참조하여 즉각 구현 및 테스트할 수 있도록 **구체적인 아키텍처 설계와 단계별 개선 명세**를 정의한다.

---

## 2. 현재 에이전트 아키텍처 및 구현 현황

### 2.1. 엔드-투-엔드 런타임 데이터 흐름
```
[Client (iOS / Web)]
       │
       ▼ (1. WebSocket /ws 또는 SSE /stream)
┌────────────────────────────────────────────────────────────────────────┐
│ FastAPI Router: tars/api/routers/chat.py                              │
│                                                                        │
│ 2. SmartSessionManager (세션 분기, 15분/2시간 시간 감쇄, 리셋/주제전환)    │
│ 3. DynamicSlicerEngine (5-Factor 점수화 기반 OKF 지식 동적 슬라이싱)    │
│ 4. TARSPersonaManager (Humor 90%, Honesty 95%, Anti-sycophancy 규제)  │
│                                                                        │
│ ─── [현재 병목 구간] ──────────────────────────────────────────────── │
│ LangGraph StateGraph (orchestrator/graph.py)를 거치지 않고,               │
│ llm_router.route_and_stream()을 직접 호출하여 단선형 텍스트만 스트리밍   │
│ ────────────────────────────────────────────────────────────────────── │
│                                                                        │
│ 5. 응답 스트리밍 완료 후 BackgroundTasks 트리거                          │
│    └── SelfEvolvingKnowledgeWorker (대화 속 새 지식/선호도 추출 ➔ OKF)  │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2. 모듈별 구현 현황 매핑
| 모듈 | 주요 파일 경로 | 현재 구현 상태 | 비고 / 한계점 |
|---|---|---|---|
| **Orchestrator** | `tars/orchestrator/graph.py`<br>`tars/orchestrator/nodes.py` | StateGraph ReAct 루프 구현 완료 (`slicer -> prompt -> llm -> tool -> llm`) | **실제 API(`chat.py`)와 미연결**, 독립 테스트로만 동작 |
| **LLM Adapters** | `tars/adapters/gemini.py`<br>`tars/adapters/llamacpp.py`<br>`tars/adapters/router.py` | 텍스트 생성(`agenerate`) 및 스트리밍(`astream`), 500ms Fallback 서킷 브레이커 구현 완료 | **실제 Tool Calling(Function Calling) 미구현** (`agenerate_response` 기본값 빈 리스트) |
| **Tools & CAG** | `tars/tools/registry.py`<br>`tars/tools/cag.py`<br>`tars/tools/google/`<br>`tars/tools/mcp/` | Google Calendar/Gmail 어댑터, MCP 클라이언트(JSON-RPC 2.0), CAG 캐시 매니저 구현 완료 | 단위 테스트 통과 상태이나, 실시간 스트리밍 대화 중 호출 불가 |
| **Dynamic Slicer** | `tars/slicer/engine.py` | 5-Factor 점수화(Context, Importance, Type, Relations, Recency) 및 1,500 토큰 패킹 완료 | 정상 동작 중 |
| **Persona** | `tars/persona/prompts.py` | Humor/Honesty 파라미터 제어, Anti-sycophancy 지침 주입 완료 | 정상 동작 중 |
| **Session** | `tars/core/session/manager.py`<br>`tars/core/session/detector.py` | 시간 감쇄 세션 분기, 자연어 리셋, 주제 전환 감지 완료 | 정상 동작 중 |
| **Knowledge Extractor**| `tars/extractor/worker.py` | 대화 턴 비동기 분석 ➔ OKF 문서 생성 ➔ DB 메타데이터 원자적 동기화 완료 | 정상 동작 중 |

---

## 3. 핵심 문제점 및 병목 지점 정밀 분석 (Gaps & Root Causes)

### 🚨 Gap 1. LangGraph ReAct 엔진과 실제 서빙 API(`chat.py`) 간의 단절
- **원인**: `tars/api/routers/chat.py`의 `chat_sse_stream` 및 `chat_websocket_endpoint`에서 `tars.orchestrator.graph.create_tars_graph()`를 사용하지 않고, 수동으로 `DynamicSlicerEngine`과 `TARSPersonaManager`를 호출한 뒤 `llm_router.route_and_stream()`을 직접 호출함.
- **코드 상의 흔적**:
  ```python
  # tars/api/routers/chat.py Line 231
  # - 향후 다단계 ReAct 도구 체이닝 확장 시, tars.orchestrator.graph.create_tars_graph()와 직접 연계할 수 있습니다.
  ```
- **문제점**: 사용자가 "내일 10시 회의 일정 확인해줘"나 "최근 메일 요약해줘"라고 발화해도 도구를 호출하는 ReAct 루프가 실행되지 않고, LLM이 추측으로 답변하거나 일반 텍스트만 출력함.

### 🚨 Gap 2. 실제 LLM 어댑터의 Function Calling(도구 호출) 미구현
- **원인**:
  1. `tars/adapters/base.py`의 `BaseLLMAdapter.agenerate_response()` 기본 구현이 `LLMResponse(content=text, tool_calls=[])`로 하드코딩되어 있음.
  2. `GeminiAdapter`(`tars/adapters/gemini.py`)가 `agenerate_response`를 오버라이드하지 않았으며, 내부 SDK 호출 함수(`_call_client_generate`, `_call_client_stream`)에서 `tools` 파라미터를 Gemini API로 전달하거나 `response.function_calls`를 `ToolCallData`로 파싱하는 로직이 완전히 누락됨.
- **문제점**: 통합 테스트(`test_langgraph_tool_react_loop.py`)는 `MockLLMAdapter`를 사용하여 통과하지만, 실제 `GeminiAdapter`를 투입하면 모델이 도구를 호출할 방법이 없음.

### 🚨 Gap 3. 스트리밍 환경(SSE/WebSocket)에서의 Tool Calling 프로토콜 부재
- **원인**: 일반적인 대화형 AI는 단일 턴 완료 후 응답하는 구조가 아니라 SSE/WebSocket으로 토큰 단위 실시간 스트리밍을 수행함.
- **문제점**:
  - 모델이 도구를 호출하기로 결정했을 때, 클라이언트로 즉시 텍스트 토큰을 보낼 수 없음 (도구 호출 인수 JSON을 사용자에게 말할 수는 없음).
  - 도구 실행 중(수백 ms ~ 수 초) 클라이언트에게 어떤 상태 이벤트를 내려줄 것인가? ("일정을 확인하는 중입니다..." 등)
  - 도구 실행 결과가 주입된 후 최종 생성되는 발화를 어떻게 스트리밍할 것인가?
  - 이에 대한 **스트리밍-에이전트 통신 이벤트 프로토콜 규격**이 정의되어 있지 않음.

### ⚠️ Gap 4. 라우터 의도 분류의 정규식 의존성
- **원인**: `tars/adapters/router.py`에서 복잡 추론과 일상 대화를 정규식 키워드(`COMPLEX_REASONING_PATTERNS`, `CASUAL_CHAT_PATTERNS`)로만 1차 분류함.
- **문제점**: 다양한 자연어 표현(한국어/영어의 변칙 구문, 문맥 의존적 질문)에서 의도 분류 오류가 발생하기 쉬움. PRD에서 명시한 "로컬 SLM(`llama.cpp`)을 활용한 고속 경량 의도 분류" 취지를 100% 살리지 못함.

### ⚠️ Gap 5. 테스트 스위트의 마이그레이션 잔재 (ImportError)
- **원인**: Phase 4에서 PostgreSQL 및 Alembic 도입 후 `tars/db/session.py`에서 `_enable_sqlite_foreign_keys`가 제거되었으나, `tests/tier1_unit/test_stress_db_reconciliation.py`에서 여전히 해당 함수를 임포트하고 있음.
- **문제점**: `pytest` 실행 시 테스트 수집(Collection) 단계에서 즉시 실패(Exit Code 2).

---

## 4. 상세 개선 방안 및 구현 명세 (Implementation Guide)

### Phase 1: 테스트 스위트 정합성 복구 (긴급 기반 정비)
- **작업 대상**: `tests/tier1_unit/test_stress_db_reconciliation.py`
- **해결 방안**:
  1. `from tars.db.session import _enable_sqlite_foreign_keys` 임포트 제거.
  2. 테스트 파일 내부에 표준 SQLAlchemy SQLite PRAGMA 이벤트 리스너 함수 정의:
     ```python
     def _enable_sqlite_foreign_keys(dbapi_con, con_record):
         cursor = dbapi_con.cursor()
         cursor.execute("PRAGMA foreign_keys=ON")
         cursor.close()
     ```
  3. `uv run pytest` 전체 실행하여 기존 테스트 스위트가 깨지지 않는지 검증.

---

### Phase 2: GeminiAdapter 실제 Function Calling 완벽 구현

`tars/adapters/gemini.py`에 Google GenAI SDK 기반의 도구 호출 바인딩 및 파싱 로직을 정식 구현한다.

#### 1) `agenerate_response` 구현 명세
```python
async def agenerate_response(
    self,
    messages: Sequence[BaseMessage],
    system_prompt: str = "",
    **kwargs: Any,
) -> LLMResponse:
    """도구 스키마(tools)를 Gemini API에 주입하고, 함수 호출 요청(function_calls)을 파싱하여 반환."""
```
- **파라미터 바인딩**:
  - `kwargs.get("tools")` 또는 `self.tools`에서 전달받은 Gemini 함수 선언 목록(`list[dict[str, Any]]`)을 `google.genai.types.GenerateContentConfig(tools=...)`에 주입.
- **결과 파싱**:
  - 모델 응답 객체에서 `response.function_calls`를 검사.
  - 함수 호출이 존재하는 경우:
    - 각 함수 호출을 `ToolCallData(id=f"call_{uuid.uuid4().hex[:8]}", name=call.name, arguments=dict(call.args))`로 변환.
    - `LLMResponse(content=response.text or "", tool_calls=tool_calls_list)` 반환.
  - 일반 텍스트 응답인 경우:
    - `LLMResponse(content=response.text or "", tool_calls=[])` 반환.

#### 2) `LlamaCppAdapter` 구조화 출력 및 툴 콜 포맷 대응
- 로컬 SLM에서도 OpenAI 호환 `tools` 스키마 전달 및 `tool_calls` 응답 파싱 로직 추가.

---

### Phase 3: 스트리밍 ReAct 에이전트 서빙 파이프라인 통합 (`chat.py`)

SSE 및 WebSocket 엔드포인트에서 단순 토큰 생성이 아닌 **ReAct 에이전트 스트리밍 프로토콜**을 구현한다.

#### 1) 클라이언트 스트리밍 이벤트 프로토콜 규격 (SSE & WS)
| Event 타입 | Payload 스키마 | 설명 |
|---|---|---|
| `stream_start` | `{"session_id": str}` | 세션 연결 및 스트림 개시 |
| `tool_start` | `{"tool": str, "call_id": str, "args": dict}` | 도구 실행 시작 안내 (UI에 로딩 상태 표시) |
| `tool_result` | `{"tool": str, "status": "success"|"error", "summary": str}` | 도구 실행 결과 요약 (필요시 UI 배지 업데이트) |
| `token` | `{"content": str, "delta": str}` | TARS의 최종 발화 텍스트 토큰 실시간 전송 |
| `stream_end` | `{"session_id": str, "content": str, "tools_used": list[str]}` | 전체 스트림 완료 및 최종 텍스트 |
| `done` | `[DONE]` | 스트림 종료 플래그 |

#### 2) `chat.py` 실행 흐름 리팩토링
```python
# tars/api/routers/chat.py 에서의 새로운 실행 흐름

# 1. 사용자 맞춤형 도구 레지스트리 생성 (활성화된 도구만 선별)
# 2. StateGraph 컴파일 (create_tars_graph)
# 3. graph.astream 또는 astream_events를 통한 실시간 처리:
#    - slicer_node -> prompt_node 실행
#    - llm_node 실행 시:
#      a. ToolCall 요청 감지 시 -> yield event: tool_start
#      b. tool_node 실행 완료 시 -> yield event: tool_result
#      c. 최종 발화 생성 시 -> yield event: token (실시간 텍스트)
# 4. DB 턴 영속화 (최종 사용자 메시지 + 어시스턴트 메시지)
# 5. BackgroundTasks -> SelfEvolvingKnowledgeWorker 실행
```

---

### Phase 4: 하이브리드 라우터(SLM + Gemini) 의도 분류 고도화

- `tars/adapters/router.py`의 정규식 의존도를 낮추고, 로컬 SLM(`llama.cpp`)에 초경량 프롬프트(JSON Schema 모드)를 전달하여 **10ms~50ms 내 초고속 의도 분류**를 수행하도록 고도화.
  ```json
  {"intent": "casual_chat" | "complex_reasoning" | "tool_required", "confidence": 0.95}
  ```
- 로컬 SLM 응답 지연/장애 시 즉각 정규식 및 Gemini 기본값으로 Fallback하는 서킷 브레이커 유지.

---

### Phase 5: E2E 에이전트 시나리오 검증 테스트 스위트 구축

실제 에이전트 지능과 도구 연동을 철저히 검증하기 위한 통합 시나리오 테스트:

1. **단일 도구 시나리오**:
   - 질문: "오늘 등록된 내 일정 알려줘."
   - 검증: `calendar_list_events` 도구 호출 -> 결과 파싱 -> TARS 톤("현재 일정 2건이 확인되었습니다, 파트너...")으로 최종 답변.
2. **다단계 도구 시나리오**:
   - 질문: "내일 오후 3시에 웜홀 궤도 계산 미팅 잡고, 쿠퍼에게 메일 보내줘."
   - 검증: `calendar_create_event` 실행 -> `gmail_send_message` 실행 -> 종합 완료 보고.
3. **도구 오류 및 페일오버(Graceful Fallback) 시나리오**:
   - 도구 API 권한 오류 또는 타임아웃 발생 시, TARS가 기계적으로 뻗지 않고 건조한 위트("캘린더 통신 모듈에 일시적 장애가 발생했습니다...")로 대처하는지 검증.
4. **대화 후 지식 자가 진화 시나리오**:
   - 대화: "앞으로 나는 아침 8시 회의는 절대 잡지 않는 규칙을 정할게."
   - 검증: 대화 종료 후 백그라운드 워커가 `rule_no_morning_8am_meeting.md` OKF 문서를 자동 생성하고 PostgreSQL 인덱스에 등록하는지 검증.

---

## 5. 업그레이드 작업 우선순위 체크리스트 (Implementation Checklist)

- [ ] **Step 1**: `tests/tier1_unit/test_stress_db_reconciliation.py` 임포트 오류 수정 및 `pytest` 전체 패스 확인
- [ ] **Step 2**: `GeminiAdapter`에 실제 GenAI SDK `tools` 바인딩 및 `agenerate_response` 구현
- [ ] **Step 3**: `LlamaCppAdapter`에 `tools` 전달 및 `tool_calls` 파싱 구현
- [ ] **Step 4**: 스트리밍 ReAct 에이전트 프로토콜 정의 및 `chat.py` (SSE/WS)에 LangGraph 실행 파이프라인 결합
- [ ] **Step 5**: 도구 호출 중간 상태(`tool_start`, `tool_result`) 스트리밍 이벤트 전송 구현
- [ ] **Step 6**: Google Calendar, Gmail, Mock MCP 도구 통합 E2E 테스트 작성 및 검증
- [ ] **Step 7**: 로컬 SLM 기반 초경량 구조화 의도 분류기 고도화 (선택/권장)
