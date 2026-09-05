# TARS 백그라운드 태스크 수명주기 및 동시성 격리 아키텍처 명세서 (BACKGROUND_TASK_REFACTORING_SPEC.md)

> **문서 상태**: Production Architecture Specification  
> **대상 모듈**: `tars.orchestrator.nodes`, `tars.services.agent_chat`, `tars.api.routers.chat`, `tars.api.app`, `tests`  
> **목적**: TARS의 백그라운드 지식 추출 태스크의 동시성 격리, 비정상 클라이언트 연결 해제 시 영구 데이터 보존 메커니즘, 서버 셧다운 시 Graceful Drain의 구현 구조 및 검증 기준을 정의합니다.

---

## 1. 아키텍처 배경 및 설계 원칙

### 1.1 해결된 핵심 과제
1. **다중 테넌트 동시성 격리**:
   - 특정 사용자의 클라이언트(WebSocket/SSE) 연결이 끊어지더라도, 백그라운드에서 실행 중인 다른 동시 접속 사용자의 지식 추출 태스크가 영향받지 않고 독립적으로 완결되도록 보장.
2. **비정상 소켓 종료 시 영구 데이터 무손실 (Zero Data Loss)**:
   - 사용자가 모델의 답변을 모두 수신한 직후 브라우저 탭을 닫아 소켓이 종료되더라도, 대화 속 중요한 사실을 OKF 마크다운 문서 및 DB로 동기화하는 백그라운드 저장이 중단 없이 완결됨.
3. **계층 분리 원칙 (SRP) 준수**:
   - 표현(Presentation) 계층인 FastAPI 라우터(`chat.py`)는 순수한 클라이언트 I/O만 전담하며, 비즈니스 계층의 비동기 백그라운드 태스크의 수명주기를 직접 들여다보거나 조작하지 않음.

### 1.2 수명주기 아키텍처 다이어그램

```mermaid
flowchart TD
    subgraph ClientLayer["[Client & Router Layer]"]
        WS[Client A 소켓 종료] --> SocketClose[소켓 세션만 안전 종료]
        SocketClose -.-> RouterClean["chat.py: 로컬 소켓 리소스만 정리"]
    end

    subgraph OrchestratorLayer["[Orchestrator Background Task Layer]"]
        NodeDispatch[nodes.py: postprocess_node] --> TaskRunA["User A 지식추출 (독립 완결)"]
        NodeDispatch --> TaskRunB["User B 지식추출 (독립 완결)"]
        TaskRunA -->|완료 시 self-discard| LocalSet["_background_node_tasks (GC 방지용 Set)"]
        TaskRunB -->|완료 시 self-discard| LocalSet
    end

    subgraph LifespanLayer["[FastAPI Application Lifespan]"]
        AppShutdown[FastAPI 서버 Shutdown / SIGTERM] --> Lifespan["lifespan context manager"]
        Lifespan -->|shutdown_background_tasks(timeout=5s)| GracefulDrain["asyncio.wait 대기 (최대 5초)"]
        GracefulDrain --> LocalSet
    end
```

---

## 2. 서브시스템별 세부 구현 명세

### 2.1. `tars/orchestrator/nodes.py` (자체 GC 방지 및 Graceful Shutdown)
- **자체 수거 콜백 등록**:
  - `execute_background_knowledge_extraction` 태스크를 디스패치할 때 `task.add_done_callback(_background_node_tasks.discard)`를 연결하여, 작업이 완료되면 스스로 set에서 제거되도록 합니다.
- **`shutdown_background_tasks(timeout: float = 5.0)`**:
  - FastAPI 서버 종료(SIGTERM) 시 호출되는 표준 헬퍼 함수.
  - 실행 중인 모든 pending 태스크를 최대 5초간 대기(`asyncio.wait`)하여 정상 완료를 보장하고, 타임아웃 초과 태스크만 안전하게 취소 및 로깅합니다.

### 2.2. `tars/api/app.py` (FastAPI Lifespan 연동)
- 애플리케이션 시작 시 DB 마이그레이션 메타데이터를 초기화하고, 종료 시 `shutdown_background_tasks()`를 호출하여 실행 중인 백그라운드 작업이 안전하게 드레인(Drain)되도록 보장합니다.
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: Database initialization
    yield
    # Shutdown: Graceful Drain pending background extraction tasks
    await shutdown_background_tasks(timeout=5.0)
    await dispose_engine()
```

### 2.3. `tars/services/agent_chat.py` (비즈니스 계층 예외 격리)
- 백그라운드 지식 추출 함수 내부에서 `asyncio.CancelledError`와 일반 `Exception`을 명확히 구분하여 구조화 로깅(`logger.error(..., exc_info=True)`)을 수행하고, 외부 호출자에게 예외가 전파되어 서비스가 중단되지 않도록 완벽히 격리합니다.

### 2.4. `tars/api/routers/chat.py` (표현 계층 책임 정돈)
- 라우터에서 `_background_ws_tasks` 전역 참조 및 강제 `cancel()` 로직이 완전히 제거되었습니다.
- 클라이언트 연결 종료 시 WebSocket 핸들러는 자신의 연결만 정리하고 백그라운드 태스크는 독립 실행 상태를 유지합니다.

---

## 3. 검증 완료된 복원력 및 회귀 테스트 스위트

다음 핵심 검증 시나리오들이 통합 테스트 스위트에 등록되어 상시 검증되고 있습니다:

1. **소켓 종료 후 백그라운드 완결 검증 (`tests/tier3_e2e_api/test_websocket_streaming.py`)**:
   - 클라이언트가 WebSocket 메시지를 보내고 중간에 연결을 강제 종료(`websocket.close()`)해도, 백그라운드 지식 추출 태스크는 취소되지 않고 100% 정상 완료되어 OKF 파일 및 DB에 저장됨.
2. **다중 유저 동시성 격리 검증 (`tests/tier1_unit/test_challenger_m1_concurrency.py`)**:
   - User A와 User B가 동시에 대화하고 User A의 소켓이 종료되어도, User B의 백그라운드 지식 추출 작업이 전혀 영향받지 않고 정상 완결됨.
3. **Lifespan Graceful Drain 검증 (`tests/orchestrator/test_shutdown_stress.py`)**:
   - 100개 이상의 동시 백그라운드 태스크가 대기 중인 상태에서 서버 종료 트리거 시 지정된 타임아웃 내에 안전하게 완료 및 정리됨.

