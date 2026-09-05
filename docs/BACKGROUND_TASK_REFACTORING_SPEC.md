# TARS 백그라운드 태스크 수명주기 및 동시성 격리 리팩토링 작업 명세서

> **문서 상태**: Active / Implementation Ready  
> **대상 모듈**: `tars.api.routers.chat`, `tars.services.agent_chat`, `tars.orchestrator.nodes`, `tars.api.app`, `tests`  
> **관련 이슈**: WebSocket 종료 시 전역 태스크 일괄 취소 버그, 동시 접속 환경 데이터 유실, 표현 계층 SRP 위반  
> **목적**: 코딩 에이전트가 단독으로 코드를 수정하고 회귀 없이 검증할 수 있도록, 문제의 근본 원인 분석부터 파일별 변경 상세 코드, 아키텍처 다이어그램, Graceful Shutdown 명세, 테스트 검증 절차까지 완결된 구현 지침을 제공합니다.

---

## 1. 배경 및 문제점 분석 (Root Cause & Problem Statement)

### 1.1 발견된 3가지 핵심 문제점

#### ① 동시 접속 시 타 유저 태스크 일괄 취소 (치명적 동시성 결함)
* **현상**: `tars.orchestrator.nodes._background_node_tasks`는 모듈 레벨의 **프로세스 전역(Global) `set`**입니다.
* **버그 메커니즘**: 유저 A와 유저 B가 동시에 접속하여 대화할 때, 유저 A가 브라우저 창을 닫아 WebSocket이 종료되면 `tars/api/routers/chat.py`의 `finally` 블록이 실행됩니다. 이때 `_background_ws_tasks` 전역 셋에 등록되어 실행 중이던 **유저 B의 지식 추출 태스크까지 모조리 `cancel()`되고 `clear()`되는 대형 장애**가 발생합니다.

#### ② 도메인 목적 불일치에 따른 영구 데이터 유실 (Data Loss)
* **현상**: '백그라운드 지식 추출'(`execute_background_knowledge_extraction`)은 대화가 끝난 후 대화 턴에서 중요한 사실(Fact)과 페르소나 정보를 추출하여 DB와 OKF(Open Knowledge Federation) 마크다운 문서로 영구 동기화하는 작업입니다.
* **버그 메커니즘**: 사용자가 모델의 답변을 모두 수신한 직후 브라우저 탭을 닫는 것은 자연스러운 사용자 행동입니다. 그러나 소켓이 닫혔다는 이유로 백그라운드 저장을 강제 중단시켜 버리면 사용자의 대화 지식이 DB에 저장되지 못하고 영구 유실됩니다.

#### ③ 계층 분리 원칙(SRP) 위반
* **현상**: 컨트롤러(라우터)는 HTTP/WebSocket 연결 수립, 프로토콜 직렬화, 클라이언트 입출력 중계만 담당하는 **표현(Presentation) 계층**입니다.
* **설계 결함**: 비즈니스 로직(지식 추출)이 생성한 비동기 작업의 수명주기를 컨트롤러가 직접 전역 변수로 들여다보고 `cancel()`을 호출하는 것은 심각한 결합도(Coupling)이자 책임 범위 위반입니다.

### 1.2 왜 이런 코드가 존재했는가? (Historical Context)
1. **Python asyncio GC 조기 수거 방지**: `asyncio.create_task()`로 생성된 태스크가 변수에 참조되지 않으면 실행 도중 가비지 컬렉터에 의해 임의 수거되는 문제가 있어 전역 `set`에 보관하게 되었습니다.
2. **테스트/서버 종료 시 경고 회피용 임시방편**: 테스트나 프로세스 종료 시 pending 태스크가 남아있으면 발생하는 `Task was destroyed but it is pending!` 경고를 급하게 막기 위해 라우터의 `finally`에 강제 취소 코드를 삽입한 레거시 흔적입니다.

---

## 2. 아키텍처 개선 원칙 (Core Principles)

```mermaid
flowchart TD
    subgraph AS_IS["[AS-IS: 위험 구조]"]
        WS1[Client A 소켓 종료] --> RouterFinally["chat.py: finally 블록"]
        RouterFinally -->|전역 Set 일괄 취소| GlobalSet["_background_ws_tasks (Global Set)"]
        GlobalSet -->|강제 중단| TaskA["User A 지식추출 (유실)"]
        GlobalSet -->|동시 취소 피해| TaskB["User B 지식추출 (유실)"]
    end

    subgraph TO_BE["[TO-BE: 정석 구조]"]
        WS2[Client A 소켓 종료] --> SocketClose[소켓 세션만 안전 종료]
        SocketClose -.독립 실행.-> TaskRunA["User A 지식추출 (백그라운드 완결)"]
        
        NodeDispatch[nodes.py: Task 디스패치] --> LocalSet["_background_node_tasks"]
        NodeDispatch --> TaskRunB["User B 지식추출 (백그라운드 완결)"]
        TaskRunA -->|완료 시 self-discard| LocalSet
        TaskRunB -->|완료 시 self-discard| LocalSet
        
        AppShutdown[FastAPI 서버 Shutdown] --> Lifespan["lifespan context manager"]
        Lifespan -->|Graceful Drain (Timeout 5s)| LocalSet
    end
```

1. **정석 1: 완전한 자체 격리 (Fire-and-Forget & Robust Error Isolation)**
   - 백그라운드 태스크 함수(`execute_background_knowledge_extraction`) 내부에서 모든 예외를 잡아서 로깅하고 완결 짓습니다.
   - 외부 라우터나 호출자가 이 태스크의 실패 여부나 수명주기를 직접 통제할 필요가 전혀 없습니다.
2. **정석 2: GC 방지는 작업 실행 주체(노드 내부)에서 자체 수행**
   - 이미 `nodes.py:643-645`에 구현된 바와 같이, `task.add_done_callback(_background_node_tasks.discard)`를 통해 작업이 끝나면 스스로 set에서 제거되도록 유지합니다.
3. **정석 3: 수명주기 제어는 오직 FastAPI Lifespan(Graceful Shutdown)에서만 수행**
   - 태스크를 대기하거나 정리해야 하는 유일한 시점은 **"웹소켓이 닫힐 때"가 아니라 "애플리케이션(FastAPI 서버) 전체가 종료될 때"**입니다.
   - 서버가 종료될 때 pending 태스크들을 지정된 타임아웃(예: 5초) 동안 안전하게 기다려주고(`asyncio.wait`), 타임아웃 초과 시에만 취소합니다.

---

## 3. 모듈별 세부 변경 명세 (Detailed File Modifications)

### 3.1 `tars/api/routers/chat.py` (표현 계층 책임 정돈)

* **파일 경로**: `tars/api/routers/chat.py`
* **수정 목적**: 라우터에서 비즈니스 백그라운드 태스크 참조 및 강제 취소 로직 전면 제거

#### (1) Import 정리
* `_background_ws_tasks` import를 제거합니다.
```python
# [변경 전]
from tars.services.agent_chat import (
    AgentChatService,
    _background_ws_tasks,
    execute_background_knowledge_extraction,
)

# [변경 후]
from tars.services.agent_chat import (
    AgentChatService,
    execute_background_knowledge_extraction,
)
```

#### (2) WebSocket `chat_stream_ws`의 `finally` 블록 제거
* `chat_stream_ws` 함수의 라인 206~216 부근의 강제 `cancel()` 및 `clear()` 블록을 완전히 제거합니다.
```python
# [변경 전]
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed for user %s", user_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket exception: %s", exc, exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if _background_ws_tasks:
            pending = [t for t in _background_ws_tasks if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                try:
                    await asyncio.gather(*pending, return_exceptions=True)
                except Exception:
                    pass
            _background_ws_tasks.clear()

# [변경 후]
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed for user %s", user_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket exception: %s", exc, exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        logger.debug("WebSocket handler connection cleaned up for user %s", user_id)
```

---

### 3.2 `tars/services/agent_chat.py` (비즈니스 계층 캡슐화 및 로깅)

* **파일 경로**: `tars/services/agent_chat.py`
* **수정 목적**: 내부 태스크 셋 노출 제거 및 백그라운드 작업 에러 가시성 향상

#### (1) Import 및 `__all__` 정리
* `from tars.orchestrator.nodes import _background_node_tasks as _background_ws_tasks` 임포트 제거.
* `__all__`에서 `"_background_ws_tasks"` 제거.

#### (2) `execute_background_knowledge_extraction` 예외 로깅 강화
* 기존에 `logger.debug`로만 처리되던 예외 처리를 운영 장애 분석이 가능하도록 `logger.error(..., exc_info=True)`로 격상.
```python
# [변경 전]
    except BaseException as exc:
        logger.debug("Background knowledge extraction ended for user %s: %s", user_id, exc)

# [변경 후]
    except asyncio.CancelledError:
        logger.warning("Background knowledge extraction cancelled for user %s", user_id)
        raise
    except Exception as exc:
        logger.error("Background knowledge extraction failed for user %s: %s", user_id, exc, exc_info=True)
```

---

### 3.3 `tars/orchestrator/nodes.py` (Graceful Shutdown 헬퍼 제공)

* **파일 경로**: `tars/orchestrator/nodes.py`
* **수정 목적**: 서버 종료 시 안전하게 백그라운드 작업을 대기 및 정리할 수 있는 표준 함수 제공

#### (1) `shutdown_background_tasks` 함수 추가
```python
async def shutdown_background_tasks(timeout: float = 5.0) -> None:
    """Gracefully wait for pending background extraction tasks during server shutdown.
    
    Args:
        timeout: Maximum seconds to wait for active tasks before cancelling.
    """
    if not _background_node_tasks:
        return

    pending = [t for t in _background_node_tasks if not t.done()]
    if not pending:
        _background_node_tasks.clear()
        return

    logger.info(
        "Shutdown initiated: waiting for %d background task(s) to finish (timeout=%.1fs)...",
        len(pending),
        timeout,
    )
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    logger.info("Background tasks shutdown: %d completed, %d timed out", len(done), len(still_pending))

    for t in still_pending:
        t.cancel()

    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)

    _background_node_tasks.clear()
```

#### (2) `__all__`에 `shutdown_background_tasks` 추가

---

### 3.4 `tars/api/app.py` (서버 Lifespan Graceful Shutdown 연동)

* **파일 경로**: `tars/api/app.py`
* **수정 목적**: FastAPI 애플리케이션 종료 시점에 `shutdown_background_tasks` 호출

```python
# [변경 후 lifespan 구현]
from tars.orchestrator.nodes import shutdown_background_tasks

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for database initialization and graceful shutdown."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Graceful Shutdown: 백그라운드 지식 추출 태스크 정상 완료 대기
    await shutdown_background_tasks(timeout=5.0)
```

---

## 4. 테스트 및 회귀 검증 명세 (Testing & Verification)

### 4.1 신규 작성/보강할 테스트 케이스
`tests/tier3_e2e_api/test_websocket_streaming.py`에 다음 시나리오를 추가합니다.

#### 시나리오 1: 소켓 연결 종료 후에도 백그라운드 태스크 완결 검증 (Resilience)
* **검증 내용**: 클라이언트가 메시지를 전송하고 스트리밍 이벤트를 받다가 WebSocket 연결을 끊었을 때(`websocket.close()`), 백그라운드 태스크가 강제 캔슬되지 않고 완료되어 DB/OKF 저장까지 도달하는지 확인.
* **단언(Assert)**:
  - `task.cancelled()`가 `False`일 것
  - `task.done()` 상태에 정상 도달할 것

#### 시나리오 2: 다중 유저 동시 접속 환경 격리성 검증 (Multi-User Isolation)
* **검증 내용**: User A와 User B가 동시에 백그라운드 지식 추출 작업을 시작함.
* **동작**: User A의 웹소켓 연결을 끊음.
* **단언(Assert)**:
  - User A의 소켓 종료 후에도 User B의 백그라운드 작업은 `cancelled()`되지 않고 계속 실행 중이거나 성공적으로 끝남.
  - 전역 셋이 `clear()`되어 User B의 작업 참조가 소실되는 현상이 전혀 발생하지 않음.

#### 시나리오 3: Lifespan Graceful Shutdown 검증
* **검증 내용**: `shutdown_background_tasks(timeout=1.0)` 호출 시 실행 중인 태스크들이 타임아웃 내에 대기 후 깔끔히 정리되는지 확인.

### 4.2 기존 테스트 스위트 회귀 검증 명령
리팩토링 후 다음 테스트들이 100% 통과해야 합니다.
```bash
# Tier 3 E2E API 테스트 (WebSocket, SSE, Streaming)
./.venv/bin/pytest tests/tier3_e2e_api/test_websocket_streaming.py -v
./.venv/bin/pytest tests/tier3_e2e_api/test_chat_streaming_extractor_adversarial.py -v

# 전체 Tier 3 테스트
./.venv/bin/pytest tests/tier3_e2e_api/ -v
```

---

## 5. 코딩 에이전트 실행 체크리스트 (Agent Step-by-Step Checklist)

- [ ] **Step 1**: `tars/orchestrator/nodes.py`에 `shutdown_background_tasks(timeout=5.0)` 구현 및 export
- [ ] **Step 2**: `tars/services/agent_chat.py`에서 `_background_ws_tasks` 참조 제거 및 `execute_background_knowledge_extraction` 예외 로깅 강화
- [ ] **Step 3**: `tars/api/routers/chat.py`에서 `_background_ws_tasks` 임포트 제거 및 `chat_stream_ws`의 `finally` 태스크 취소 로직 삭제
- [ ] **Step 4**: `tars/api/app.py`의 `lifespan`에 `shutdown_background_tasks()` 호출 연동
- [ ] **Step 5**: `tests/tier3_e2e_api/test_websocket_streaming.py`에 동시성 격리 및 소켓 종료 복원력 테스트 추가
- [ ] **Step 6**: pytest 실행을 통한 회귀(Regression) 및 전체 테스트 통과 확인
