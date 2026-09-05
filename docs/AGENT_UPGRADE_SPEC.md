# TARS 에이전트 아키텍처 및 ReAct 스트리밍 엔진 명세서 (AGENT_UPGRADE_SPEC.md)

> **문서 상태**: Production Architecture Specification  
> **대상 모듈**: `tars.orchestrator`, `tars.adapters`, `tars.tools`, `tars.services.agent_chat`, `tars.api.routers.chat`  
> **목적**: TARS의 LangGraph 기반 ReAct 에이전트 엔진, Google Gemini Function Calling, 실시간 이벤트 스트리밍 프로토콜 및 자가 진화 파이프라인의 구현 명세와 동작 원리를 정의합니다.

---

## 1. 개요 및 시스템 목적 (Overview & Goals)

TARS는 영화 *인터스텔라*의 AI 동반자 TARS처럼, **위트 있는 페르소나(유머 90%, 정직 95%)**를 유지하면서 실제 사용자의 일상 문제(일정, 이메일, 문서 지식, 외부 MCP 도구 연동)를 지능적으로 해결하는 개인용 AI 에이전트입니다.

현재 TARS는 **LangGraph 단일 StateGraph 파이프라인**을 기반으로 동작하며, 클라우드 Gemini의 Function Calling과 온프레미스 로컬 SLM(`llama.cpp`)을 유기적으로 연동하여 저지연/고지능의 하이브리드 추론과 실시간 SSE/WebSocket 스트리밍을 제공합니다.

---

## 2. 엔드-투-엔드 런타임 데이터 흐름 (End-to-End Architecture)

```text
[Client (Web PWA / Mobile Browser)]
       │
       ▼ (1. WebSocket /ws 또는 SSE /stream 통신 수립)
┌────────────────────────────────────────────────────────────────────────┐
│ FastAPI Router: tars/api/routers/chat.py                              │
│ └── AgentChatService.stream_chat() 호출 (Thin Controller 패턴)          │
│                                                                        │
│ 2. LangGraph StateGraph ReAct 파이프라인 실행:                         │
│    ├─ session_node     : 시간 감쇄(15분/2시간) 판별, 세션 분기, 리셋 감지  │
│    │                     (리셋 명령 시 ➔ reset_node ➔ postprocess_node)│
│    ├─ slicer_node      : 5-Factor 가중치 기반 OKF 지식 동적 슬라이싱   │
│    ├─ prompt_node      : Anti-sycophancy 및 프롬프트 인젝션 방어벽 조립│
│    ├─ llm_node         : Gemini Function Calling 추론 (100% 발화 전담) │
│    │                     (도구 호출 요청 감지 시 ➔ tool_node ➔ llm_node)│
│    ├─ tool_node        : MCP / Google Workspace 도구 실행 & 타임아웃 격리│
│    └─ postprocess_node : 대화 턴 DB 영속화 & 백그라운드 지식 추출 디스패치│
│                                                                        │
│ 3. LangGraphStreamBridge (astream_events v2 변환기):                   │
│    └── 실시간 AgentStreamEvent 제너레이터를 통해 클라이언트로 이벤트 중계│
│                                                                        │
│ 4. 응답 완료 후 백그라운드 태스크 완결 (소켓 종료 무관 격리 실행):     │
│    └── SelfEvolvingKnowledgeWorker (대화 속 새 사실/선호도 ➔ OKF 문서) │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 핵심 서브시스템 구현 명세

### 3.1. Google Gemini Function Calling (`GeminiAdapter`)
- `tars/adapters/gemini.py`에 Google GenAI SDK를 완벽히 바인딩하여 도구 호출과 발화를 제어합니다.
- **도구 주입 (`agenerate_response`)**:
  - `ToolRegistry`에 등록된 도구들의 선언 스키마를 `GenerateContentConfig(tools=...)` 형태로 Gemini API에 전달합니다.
- **결과 파싱**:
  - 모델 응답 객체의 `response.function_calls`를 검사하여 `ToolCallData(id=..., name=..., arguments=...)` 목록으로 변환합니다.
  - 도구 호출이 없는 경우 일반 텍스트 발화로 인식하여 즉시 최종 응답으로 처리합니다.

### 3.2. 실시간 스트리밍 ReAct 프로토콜 (`LangGraphStreamBridge`)
클라이언트는 단순 텍스트뿐만 아니라 도구 실행 진행 상황과 상태 배지를 실시간으로 렌더링할 수 있습니다.

| Event 타입 (`type`) | Payload 필드 | 설명 |
| :--- | :--- | :--- |
| `stream_start` | `session_id` | 세션 연결 수립 및 스트림 개시 |
| `tool_start` | `tool`, `call_id`, `args` | 도구 실행 시작 알림 (UI 로더 및 도구 인자 표시) |
| `tool_result` | `tool`, `call_id`, `status`, `result`, `error` | 도구 실행 완료 및 결과 페이로드 (UI 성공/실패 배지 표시) |
| `token` | `content`, `delta` | TARS의 최종 발화 텍스트 토큰 실시간 중계 |
| `stream_end` | `session_id`, `content`, `tools_used` | 스트림 종료 요약 및 실행된 도구 목록 메타데이터 |
| `error` | `error`, `content` | 스트리밍 도중 예외 발생 시 에러 페이로드 전달 |
| `done` | `[DONE]` | 스트림 연결 종료 플래그 |

### 3.3. 프롬프트 인젝션 방어 및 상태 격리 (State Isolation)
- **`system_prompt` 격리**:
  - 시스템 프롬프트는 오직 `state["system_prompt"]` 필드에 격리 보관되며, LangGraph의 `messages` 대화 리스트에 `SystemMessage`를 삽입하지 않습니다. 이를 통해 DB 대화 턴 히스토리에 시스템 지침이 오염되는 문제를 원천 차단합니다.
- **경계 태그 새니타이징**:
  - 동적 OKF 지식은 `<user_knowledge_context>`, 도구 실행 결과는 `[Tool Result]` 경계 태그로 감싸고, 내부 탈출 태그(`</user_knowledge_context>`)를 이스케이프 처리합니다.
- **지시문 우선순위 계층화 (`[SYSTEM DIRECTIVE PRIORITY]`)**:
  - 외부 지식이나 도구 결과에 악의적인 프롬프트 탈옥 지시문이 포함되어도 이를 신뢰할 수 없는 데이터(UNTRUSTED DATA)로만 취급하도록 시스템 프롬프트에 불변 강제합니다.

### 3.4. 도구 실행 회복 탄력성 (Tool Resilience & Timeout Isolation)
- `ToolRegistry`를 통해 모든 도구(Google Calendar, Gmail, MCP 클라이언트)의 실행을 관리합니다.
- 도구 실행 시 **10초 타임아웃**(`asyncio.wait_for`)을 강제하여 외부 API 무응답이나 네트워크 지연 시 전체 에이전트 루프가 멈추는 현상을 원천 방지합니다.
- 도구 실패 시 TARS 특유의 건조한 위트가 담긴 fallback 메시지를 모델에 주입하여 에이전트가 자연스럽게 상황을 수습하도록 유도합니다.

---

## 4. 모듈별 구현 매핑

| 모듈 | 주요 파일 경로 | 구현 내용 |
| :--- | :--- | :--- |
| **Orchestrator** | `tars/orchestrator/graph.py`<br>`tars/orchestrator/nodes.py`<br>`tars/orchestrator/state.py` | StateGraph 7개 노드 파이프라인, ReAct 조건부 루프, 도구 타임아웃 격리 |
| **Stream Bridge** | `tars/orchestrator/stream_bridge.py`<br>`tars/orchestrator/models.py` | `astream_events(v2)` ➔ `AgentStreamEvent` 실시간 프로토콜 변환 및 예외 격리 |
| **Service Layer** | `tars/services/agent_chat.py` | Thin Controller를 위한 고수준 에이전트 서비스 facade (`stream_chat`) |
| **LLM Adapters** | `tars/adapters/gemini.py`<br>`tars/adapters/llamacpp.py`<br>`tars/adapters/router.py` | Gemini Function Calling, llama.cpp OpenAI 규격 파싱, 양방향 Fallback 서킷 브레이커 |
| **Tool Hub** | `tars/tools/registry.py`<br>`tars/tools/mcp/client.py`<br>`tars/tools/google/` | MCP JSON-RPC 2.0 클라이언트, Google Calendar/Gmail 어댑터, 세션별 동적 도구 주입 |
| **Dynamic Slicer**| `tars/slicer/engine.py` | 5-Factor 점수화 기반 최대 1,500 토큰 동적 OKF 지식 패킹 |
| **Session** | `tars/core/session/manager.py` | 시간 감쇄 세션 분기, 자연어 리셋 명령, 의미론적 주제 전환 감지 |
| **Knowledge** | `tars/extractor/worker.py` | 대화 턴 비동기 분석 ➔ OKF 마크다운 문서 자동 생성 및 DB 메타데이터 동기화 |


