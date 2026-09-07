# Google OAuth 토큰 이중 갱신 방지 및 동시성 제어 아키텍처 가이드

본 문서는 TARS 백엔드에서 다중 사용자 환경 및 병렬 에이전트 실행 시 발생할 수 있는 **OAuth 토큰 이중 갱신(Duplicate Token Refresh / Thundering Herd) 문제**의 배경, 설계 원칙, 구현 패턴 및 테스트 가이드를 정의합니다. 

향후 코딩 에이전트 및 개발자가 외부 SaaS/OAuth 연동 도구(Google Workspace, GitHub, Slack 등)를 확장하거나 유지보수할 때 본 문서를 표준 아키텍처 규칙으로 참조합니다.

---

## 1. 배경 및 문제 정의 (Background & Problem Definition)

### 1.1 현상
- TARS의 LangGraph ReAct 에이전트 파이프라인에서 단일 사용자 요청에 대해 여러 도구가 병렬로 실행되거나(`calendar_list_events`, `gmail_search_messages`), 짧은 주기로 연속 호출될 수 있습니다.
- 특정 사용자의 Google OAuth Access Token이 만료되었거나 캐시에 없는 시점에 여러 코루틴이 동시에 `get_access_token(user_id)`을 호출하면, 다음과 같은 **Thundering Herd(동시 갱신 경합)** 현상이 발생합니다:

```
[Coroutine 1] ──(Cache Miss)──> [DB Lookup] ──> [Google Token API POST] ──> [Update Cache]
[Coroutine 2] ──(Cache Miss)──> [DB Lookup] ──> [Google Token API POST] ──> [Update Cache]
[Coroutine 3] ──(Cache Miss)──> [DB Lookup] ──> [Google Token API POST] ──> [Update Cache]
```

### 1.2 영향도 및 위험성
1. **보안성**: 타 사용자 간 데이터 격리(`user_id` 기준 필터링)는 유지되므로 보안 취약점(Cross-user Data Leak)은 아님.
2. **비용 및 안정성 (핵심 문제)**:
   - **Google OAuth Rate Limit 소진**: 짧은 시간에 동일 Refresh Token으로 중복 갱신 요청이 전송되어 Google API Quota가 낭비되고 일시적 `429 Too Many Requests`가 발생할 수 있음.
   - **네트워크 레이턴시 증가**: 불필요한 외부 HTTP 왕복 통신(100~300ms)이 중복 발생하여 응답 속도 저하.
   - **토큰 상태 불일치**: Google OAuth 엔드포인트의 응답 순서에 따라 발급된 최신 Access Token이 덮어쓰여져 간헐적인 인가 오류 유발 가능.

---

## 2. 핵심 설계 원칙 (Core Architectural Patterns)

이 문제를 해결하기 위해 TARS는 **사용자별 락 파티셔닝(Per-User Lock Partitioning)**과 **Double-Checked Locking** 패턴을 결합하여 적용했습니다.

### 2.1 사용자별 락 격리 (Per-User Lock Partitioning)
- **글로벌 락의 한계**: 인스턴스 전체에 단일 `asyncio.Lock()`을 걸면, 사용자 A의 토큰 갱신(네트워크 통신 포함) 동안 무관한 사용자 B, C의 도구 호출까지 모두 블로킹되는 **Head-of-Line Blocking**이 발생합니다.
- **해결책**: `user_id`를 키로 하는 독립적인 비동기 락(`self._user_locks[user_id]`)을 동적으로 할당하여, 서로 다른 사용자의 요청은 완전한 병렬 처리를 보장합니다.

### 2.2 Double-Checked Locking 흐름
동일 사용자의 요청에 대해 최소한의 락 대기와 제로 중복 네트워크 요청을 보장합니다:

```
                     get_access_token(user_id)
                               │
                               ▼
               ┌───────────────────────────────┐
               │ 1. Fast-Path 캐시 검사         │
               │    (Lock 대기 없이 즉시 조회)   │
               └───────────────┬───────────────┘
                               │
                  캐시 유효? ──┴──> [YES] ──> 0ms 즉시 토큰 반환
                               │ [NO]
                               ▼
               ┌───────────────────────────────┐
               │ 2. Per-User Lock 획득         │
               │    async with lock(user_id):  │
               └───────────────┬───────────────┘
                               │
                               ▼
               ┌───────────────────────────────┐
               │ 3. Double-Check 캐시 재검사   │
               │    (앞선 코루틴이 갱신했는가?)   │
               └───────────────┬───────────────┘
                               │
                  캐시 유효? ──┴──> [YES] ──> 갱신된 토큰 즉시 반환
                               │ [NO]
                               ▼
               ┌───────────────────────────────┐
               │ 4. 엄격한 단 1회 갱신 수행    │
               │    - DB TARSSettings 조회     │
               │    - Google Token API 교환    │
               │    - 캐시에 새 토큰 저장      │
               └───────────────┬───────────────┘
                               │
                               ▼
                          새 토큰 반환
```

---

## 3. 표준 코드 레퍼런스 (Implementation Reference)

### 3.1 `GoogleAuthHelper` (`tars/tools/google/auth.py`)

```python
import asyncio
import time
from typing import Any
import httpx

class GoogleAuthHelper:
    def __init__(self, ...):
        # 1. 멀티테넌트 사용자별 토큰 캐시: user_id -> (access_token, expires_at_timestamp)
        self._user_token_cache: dict[str, tuple[str, float]] = {}
        # 2. 사용자별 비동기 락 레지스트리
        self._user_locks: dict[str, asyncio.Lock] = {}

    def _get_user_lock(self, user_id: str | None) -> asyncio.Lock:
        """사용자별 독립 Lock 반환 (키별 파티셔닝)."""
        key = user_id or "__default__"
        if key not in self._user_locks:
            self._user_locks[key] = asyncio.Lock()
        return self._user_locks[key]

    def invalidate_user_cache(self, user_id: str) -> None:
        """연동 해제, Mock 토글, 자격 증명 수정 시 캐시 및 락 정리."""
        self._user_token_cache.pop(user_id, None)
        self._user_locks.pop(user_id, None)

    async def get_access_token(self, user_id: str | None = None) -> str:
        if self.mock_mode:
            return "mock_google_oauth2_access_token"

        now = time.time()

        # Step 1. Fast-path: 락 획득 없이 인메모리 캐시 조회 (60초 안전 버퍼 유지)
        if user_id:
            cached = self._user_token_cache.get(user_id)
            if cached and now < (cached[1] - 60):
                return cached[0]
        else:
            if self._cached_token and now < (self._token_expires_at - 60):
                return self._cached_token

        # Step 2. 해당 사용자 전용 락 획득 (타 사용자 영향 없음)
        lock = self._get_user_lock(user_id)
        async with lock:
            now = time.time()
            # Step 3. Double-check inside lock (선행 코루틴이 갱신했을 경우 즉시 반환)
            if user_id:
                cached = self._user_token_cache.get(user_id)
                if cached and now < (cached[1] - 60):
                    return cached[0]
            else:
                if self._cached_token and now < (self._token_expires_at - 60):
                    return self._cached_token

            # Step 4. 실제 DB 조회 및 Google Token API 교환 수행
            # ... DB 조회 및 유효성 검증 ...
            resp = await client.post("https://oauth2.googleapis.com/token", data=payload)
            resp.raise_for_status()
            data = resp.json()
            access_token = str(data["access_token"])
            expires_in = int(data.get("expires_in", 3600))

            # 캐시 저장
            if user_id:
                self._user_token_cache[user_id] = (access_token, now + expires_in)
            else:
                self._cached_token = access_token
                self._token_expires_at = now + expires_in

            return access_token
```

### 3.2 캐시 무효화 생명주기 연동 (`tars/api/routers/tools.py`)

다음 세 가지 이벤트 발생 시 `ToolRegistry.invalidate_user_google_cache(user_id)`를 반드시 호출해야 합니다:
1. `POST /api/v1/tools/auth/google/disconnect`: 계정 연동 해제 시
2. `POST /api/v1/tools/auth/google/credentials`: 사용자 커스텀 OAuth 클라이언트 키 변경 시
3. `POST /api/v1/tools/auth/google/mock-link`: 오프라인 모의 연동 상태 토글 시
4. `GET /api/v1/tools/auth/google/callback`: OAuth 리다이렉트 콜백을 통해 새 토큰이 수신 및 저장될 때

---

## 4. 검증 테스트 패턴 (Testing Pattern)

코딩 에이전트는 동시성 및 토큰 갱신 로직 수정 시 `tests/tier1_unit/test_multi_user_isolation.py`에 구현된 다음 패턴으로 테스트를 작성/검증해야 합니다.

### 동시 갱신 중복 방지 테스트 예시
```python
@pytest.mark.asyncio
async def test_concurrent_token_refresh_single_execution(monkeypatch, multi_user_db):
    """동일 사용자에 대해 10개 동시 요청 시 Google Token 갱신 요청이 정확히 1번만 발생하는지 검증."""
    network_call_count = 0

    class MockHttpClient:
        async def post(self, url, data=None, **kwargs):
            nonlocal network_call_count
            network_call_count += 1
            await asyncio.sleep(0.05)  # 실제 네트워크 레이턴시 시뮬레이션
            return MockResponse({"access_token": "new_tok", "expires_in": 3600})

    helper = GoogleAuthHelper(mock_mode=False, http_client=MockHttpClient())

    # 동일 사용자에 대해 동시에 10개 코루틴 실행
    tokens = await asyncio.gather(*[
        helper.get_access_token(user_id="user_c_id") for _ in range(10)
    ])

    # 1. 10개 요청 모두 유효한 새 토큰을 수신해야 함
    assert all(t == "new_tok" for t in tokens)
    # 2. Double-checked locking 덕분에 실제 네트워크 호출은 정확히 1회만 발생해야 함
    assert network_call_count == 1
```

---

## 5. 코딩 에이전트 작업 체크리스트 (Agent Guidelines)

새로운 외부 서비스(Slack, Notion 등) 인증 헬퍼를 추가하거나 기존 인증 모듈을 수정할 때 아래 체크리스트를 준수하십시오:

- [ ] **DB 조회 격리**: 토큰 조회 시 반드시 `where(Model.user_id == user_id)` 조건을 강제하여 타 사용자 토큰 누출을 방지할 것.
- [ ] **락 파티셔닝**: 전역 락(`asyncio.Lock()`) 대신 `dict[str, asyncio.Lock]` 형태의 사용자별 격리 락을 사용할 것.
- [ ] **Double-Checked Locking 준수**:
  1. 락 획득 전 Fast-Path 캐시 검사
  2. 락 획득 후 Double-Check 캐시 검사
  3. 미스 시에만 외부 API 갱신 호출
- [ ] **토큰 만료 버퍼**: `expires_at`에서 최소 60초의 여유 버퍼(`now < exp - 60`)를 두고 사전 갱신할 것.
- [ ] **캐시 무효화 엔드포인트 연결**: 인증 정보 변경/해제/재인증 시 레지스트리 및 헬퍼의 캐시 파기 메서드를 누락 없이 호출할 것.
- [ ] **동시성 단위 테스트 작성**: `asyncio.gather`를 활용해 동시 실행 시 네트워크 호출 횟수가 1회인지 단위 테스트로 입증할 것.
