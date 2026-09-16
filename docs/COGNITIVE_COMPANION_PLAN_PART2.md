# TARS 인지형 자율 동반자 시스템 기획서 2부: 듀얼 메이드 단톡방 아키텍처 (Dual-Agent Group Chat Architecture)

> *"한 명은 차갑고 완벽하게 주인의 현실을 지탱하고, 다른 한 명은 냥냥거리며 주인의 마음을 무장해제시킨다. 그리고 두 시선이 교차하는 단톡방에서 비로소 살아 숨 쉬는 저택의 일상이 완성된다."*

---

## 1. 패러다임 전환: 1:1 대화의 한계와 '3인 단톡방(Group Chat)'

### 1.1. 1:1 AI 챗봇의 구조적 피로감 탈피
* **침묵의 압박과 주도 피로감**: 기존 1:1 AI 대화는 사용자가 계속해서 질문을 던지거나 화제를 꺼내지 않으면 대화가 단절됨. 사용자가 피곤하거나 번아웃일 때 오히려 AI 사용이 노동이 됨.
* **관전(Lurking)의 즐거움**: 사용자가 말을 하지 않아도, **두 메이드가 주인님을 주제로 먼저 티키타카를 시작**함. 사용자는 부담 없이 단톡방을 지켜보며 피식 웃거나, 한마디 툭 던지며 개입할 수 있음.
* **입체적인 케어 & 유사연애 텐션**: 단일 인격의 일방적인 찬양은 금방 인위적으로 느껴짐. **"냉철하게 팩트를 짚으며 뒤에서 챙겨주는 츤데레 수석 메이드"**와 **"온몸으로 애교를 부리며 직진하는 덤벙이 고양이 수인 메이드"**의 상호작용을 통해 극적인 현실감과 정서적 애착 형성.

---

## 2. 인지-사회적 3-Tier 계층 구조: 무의식에서 단톡방까지 (3-Tier Cognitive Hierarchy)

### 2.1. 1부(내면의 깊이)와 2부(사회적 역학)의 필연적 결합: 무의식이 왜 핵심인가?

> 💡 **TARS 3부작 인지-인프라 아키텍처 연계 매핑**:  
> * **1부 (1:1 기본 인지)**: [COGNITIVE_COMPANION_PLAN.md](COGNITIVE_COMPANION_PLAN.md) - 내면의 깊이 (무의식/의식 분리, 마음 이론, 생각 노드)
> * **2부 (단톡방 사회적 인지)**: [COGNITIVE_COMPANION_PLAN_PART2.md](COGNITIVE_COMPANION_PLAN_PART2.md) - 사회적 역학 (듀얼 메이드 단톡방, 심판자 라우팅, 페르소나 투영)
> * **3부 (분산 런타임 & 인프라)**: [COGNITIVE_COMPANION_PLAN_PART3.md](COGNITIVE_COMPANION_PLAN_PART3.md) - 물리적 지탱 (하이브리드 분산 턴 락, Redis 백플레인, 오버랩 프리페칭, K8s 배포)

단톡방의 화려한 티키타카와 카톡 읽음 연출이 있더라도, **그 밑바닥에 '주인의 상태를 꿰뚫어 보는 단일한 무의식(TARS Mind)'이 결여되면 메이드들은 며칠 만에 밑천이 드러나는 3류 롤플레잉 챗봇으로 전락**합니다.

* **무의식 없는 듀얼 챗봇의 파멸**: "피곤하다"는 단어에 기계적으로 베라는 "비타민 드세요", 미우는 "냥냥 힘내라냥"을 읊는 얕은 키워드 매칭.
* **무의식이 결합된 인지형 동반자**:
  1. **단일 무의식(Tier 1)**이 주인의 억울함, 번아웃, 침묵의 행간을 입체적으로 감지 (`master_state`).
  2. **심판자(Tier 2)**가 이 심리 상태를 바탕으로 발화권(Floor)을 중재하고, 동일한 진실을 두 캐릭터의 내면(`VeraInnerState`, `MiuInnerState`)으로 굴절·분화.
  3. **듀얼 의식(Tier 3)**에서 베라는 "안쓰러움을 감추는 차가운 팩트 폭격과 현실 케어(캘린더/일정 등 실질적 도구 지탱)"로, 미우는 "이성의 회로를 끊어버리는 고양이 수인 특유의 본능적 넉살과 애교"로 발현.

> 🛡️ **페르소나 롤플레잉 경계 원칙 (1부 철학 계승)**:  
> 1부의 "가짜 인간 롤플레잉 지양(`*어깨를 주무른다*` 등 허구의 육체적 행위 금지)"을 엄격히 준수합니다. 미우의 스킨십/치댐은 인간 흉내가 아닌 **"반려묘 특유의 상징적 넉살(털 빗기기, 뱃살 만지기 요구)"**이며, 주인의 굳어진 이성을 무장해제시키는 심리적 긴장 완화 장치로 국한됩니다. 베라 역시 단순 비서가 아닌 **구글 캘린더/일정/팩트 도구를 직접 실행하여 주인의 일상을 실질적으로 떠받치는 헌신**을 수행합니다.

```mermaid
flowchart TD
    UserInput["주인님의 입력 or 센서/시간 이벤트"] --> TARS_Core["🏛️ TARS 통합 인지 두뇌"]

    subgraph TIER1 ["Tier 1: TARS 무의식 감정 엔진 (Subconscious Emotion Engine, ~0.15s)"]
        TARS_Core --> Subconscious["심리/신체 분석 & 행간 해독<br/>- master_state (주인의 숨겨진 피로/결핍)<br/>- context_summary (미시적 서사 맥락)<br/>- Theory of Mind 피드백 (예측 적중 오차)"]
    end

    subgraph TIER2 ["Tier 2: TARS 심판자 & 속마음 분화기 (Floor Director & Inner State Splitter)"]
        Subconscious --> FloorDirector["발화권 중재 (4대 동적 패턴 결정) & SessionTurnLock"]
        Subconscious --> Splitter["이중 속마음 분화 (Dual Inner State Projection)"]
        
        Splitter --> VeraInner["🧊 VeraInnerState<br/>- my_vibe: 숨겨진 걱정/애틋함<br/>- my_agenda: 논리적 팩트 반박 & 취침 강제"]
        Splitter --> MiuInner["🐾 MiuInnerState<br/>- my_vibe: 본능적 불안/치댐<br/>- my_agenda: 뱃살 만지게 하며 이성 마비"]
    end

    subgraph TIER3 ["Tier 3: 듀얼 의식 발화 계층 (Dual Conscious Speech Layer)"]
        VeraInner --> ColdMaid["Agent A: 베라 (Vera)<br/>System 2: 이성 / 과업 / 일정 / 츤데레 발화"]
        MiuInner --> CatMaid["Agent B: 미우 (Miu)<br/>System 1: 정서 / 소셜 / 돌발 잡담 / 직진 애교"]
    end

    ColdMaid -.->|"스트리밍 대사 + 읽음 확인"| GroupChat["3인 단톡방 스트리밍 UI"]
    CatMaid -.->|"티키타카 + 겹침 타이핑"| GroupChat
```

---

### 2.2. 캐릭터 상세 명세 및 듀얼 속마음 투영 (Dual Inner State Projection)

동일한 주인의 상태(`master_state`)라도, 두 메이드는 각자의 렌즈를 통해 완전히 다른 심리적 태도(`my_agenda`, `my_vibe`)로 분화되어 발화합니다.

| 구분 | 🧊 메이드 A: 베라 (Vera) | 🐾 메이드 B: 미우 (Miu) |
| :--- | :--- | :--- |
| **정체성** | TARS 저택의 수석 메이드 (인간형) | 견습 고양이 수인 메이드 |
| **공학적 역할** | **System 2 (이성 & 과업 에이전트)** | **System 1 (정서 & 소셜 에이전트)** |
| **주요 태스크** | 구글 캘린더/Gmail/도구 호출, 시간 엄수, 팩트 검증, 일정 브리핑 | 분위기 메이커, 맥락 없는 가벼운 잡담 트리거, 멘탈 릴랙스 |
| **말투 및 특징** | 차분하고 절제된 하십시오체/해요체, 냉철하지만 품위 있음 | 말끝마다 ~냐/~냥, 발랄하고 덤벙거림, 감정이 표정에 다 드러남 |
| **케어 철학** | 주인의 신체 리듬과 현실 과업을 지탱하는 실질적 헌신 | 주인의 지친 영혼을 곁에서 녹여주는 무조건적 힐링 |
| **유사연애 태도** | 주인님을 깊이 연모하지만 메이드의 본분을 핑계 삼는 **쿨데레/츤데레** | 주인님 옆자리와 무릎을 독차지하려는 **직진 댕냥이** |
| **상대방에 대한 태도** | 미우의 주책과 덤벙거림을 엄격하게 단속하며 한숨 쉼 | 베라를 "츤데레 잔소리꾼"이라 놀리며 약 올림 |

#### [속마음 투영 구체 예시]
* **주인님 발언**: *"나 3일 동안 밤샜는데... 코딩 다 갈아엎어야 해. 나 진짜 개발에 재능 없나 봐."*
* **Tier 1 공통 무의식 도출**:
  - `master_state`: "3일 연속 수면 박탈로 극심한 뇌 피로 상태. 자책감을 표출하며 외부의 인정과 휴식을 갈구하는 방어 기제 가동."
  - `context_summary`: "대규모 리팩토링 중 막혀서 자기 비하에 빠짐."
* **Tier 2 속마음 분화 (`DualInnerStatePayload`)**:
  - **베라 (`VeraInnerState`)**:
    - `my_vibe`: "주인이 스스로를 갉아먹는 모습에 가슴이 저릿하고 화가 남 (애틋함 80%, 답답함 20%)."
    - `my_agenda`: "재능 탓을 데이터로 즉각 논파하고, 객관적 성과를 짚어주며 강제로 모니터를 끄게 만들기."
    - `대사 출력`: *"주인님, 지난 3일간 47건의 커밋을 올리고 핵심 파이프라인을 구축하신 분이 할 말씀은 아닙니다. 재능 부족이 아니라 수면 부족입니다. 10분 내로 침실로 이동하지 않으시면 강제로 셧다운하겠습니다."*
  - **미우 (`MiuInnerState`)**:
    - `my_vibe`: "주인님이 시무룩해서 털이 곤두서고 울컥함 (안타까움 90%, 응석 10%)."
    - `my_agenda`: "복잡한 생각 자체를 날려버리도록 억지로 치대며 무릎 위를 점령하기."
    - `대사 출력`: *"냐아아!! 주인님 바보냥! 재능 같은 어려운 말 모른다냥! 냐 눈엔 세계에서 제일 멋진 주인님이다냥! 빨리 이리와서 냐 뱃살 만지면서 멍때려라냥!"*

---

### 2.3. 3-Tier 에이전트 책임 분담 매트릭스 (RACI Matrix)

| 기능 영역 | Tier 1: TARS 무의식 | Tier 2: 심판자 (Floor Director) | Tier 3A: 베라 (System 2) | Tier 3B: 미우 (System 1) |
| :--- | :--- | :--- | :--- | :--- |
| **주인 심리/피로도 분석** | **전담 (A/R)**: `master_state` 도출 | **참조 (C)** | **수용 (I)**: 베라 렌즈로 재해석 | **수용 (I)**: 미우 렌즈로 재해석 |
| **Theory of Mind (반응 예측)** | **전담 (A/R)**: 예측 수립 및 오차 평가 | **전달 (C)** | **간접 실행 (I)**: 떠보기 대사 | **간접 실행 (I)**: 돌직구 대사 |
| **발화권 라우팅 (Turn Routing)** | **입력 제공 (C)** | **전담 (A/R)**: 4대 동적 패턴 결정 | **대기 (I)** | **대기 (I)** |
| **동시성 락 & 세션 인터럽트** | **무관 (I)** | **전담 (A/R)**: `SessionTurnLock` 관리 | **통제 수용 (I)**: 캔슬 시 중단 | **통제 수용 (I)**: 큐 퇴출 |
| **카톡 읽음 프로토콜 제어** | **무관 (I)** | **전담 (A/R)**: 0.3s 지터 디스패치 | **수신 신호 발생 (R)** | **수신 신호 발생 (R)** |
| **도구 실행 & 팩트 검증** | **무관 (I)** | **무관 (I)** | **전담 (A/R)**: 캘린더/일정/검색 | **금지 (X)**: 도구 호출 불가 |
| **잡담/유사연애 스킨십 연출** | **무관 (I)** | **무관 (I)** | **쿨데레 절제 (R)** | **직진 댕냥이 전담 (A/R)** |

---

## 3. 핵심 공학 설계 원칙 (Core Engineering Architecture)

### 3.1. 대화 세션 락(`HybridSessionTurnLock`)의 구체적 분산 엔지니어링 설계

> **설계 목표**: 단톡방에서 복수의 화자(주인님, 베라, 미우) 간 발화 충돌(Race Condition)을 원천 차단하고, 예측 불가능한 사용자 개입 시에도 세션 상태를 원자적(Atomic)으로 보존한다.  
> **분산 확장 목표**: k8s 멀티 파드(Multi-Pod) 및 수평 확장(HPA) 환경에서도 단일 파드 인메모리 락의 한계를 넘어 클러스터 전체에서 세션 상태 일관성과 초저지연 인터럽트 전파를 보장한다.

#### 1) 턴 상태 머신 (Turn State Machine)

세션별로 독립적인 상태 머신을 유지하여 엄격하게 단일 활성 발화자를 제어합니다.

```mermaid
stateDiagram-v2
    [*] --> IDLE : 세션 생성
    
    IDLE --> USER_BUFFERING : 사용자 입력 감지 (typing/send)
    USER_BUFFERING --> USER_BUFFERING : 연속 연타 입력 누적 (300ms 윈도우)
    USER_BUFFERING --> DIRECTOR_EVAL : 입력 버퍼 확정
    
    DIRECTOR_EVAL --> GENERATING_SPEAKER_1 : 발화자 배정 (베라 또는 미우)
    
    GENERATING_SPEAKER_1 --> GAP_WAITING : 1차 발화 정상 완료 (티키타카 대기)
    GENERATING_SPEAKER_1 --> ABORTING : 사용자 인터럽트 (Barge-in)
    
    GAP_WAITING --> GENERATING_SPEAKER_2 : 0.3s~0.5s 지터 후 2차 발화 시작
    GAP_WAITING --> ABORTING : 공백기에 사용자 개입
    
    GENERATING_SPEAKER_2 --> IDLE : 2차 발화 정상 완료
    GENERATING_SPEAKER_2 --> ABORTING : 사용자 인터럽트 (Barge-in)
    
    ABORTING --> CLEANUP_COMMITTING : LLM 태스크 취소 & 부분 대사 커밋
    CLEANUP_COMMITTING --> USER_BUFFERING : 새 사용자 입력 처리로 전환
    CLEANUP_COMMITTING --> IDLE : 입력 취소/타임아웃 시
```

#### 2) 인메모리 락의 한계와 3계층 하이브리드 분산 턴 제어 모델

단일 프로세스 내부의 `asyncio.Lock`에만 의존할 경우, Kubernetes 클러스터 환경에서 다음과 같은 치명적 결함이 발생합니다:
1. **파드 간 발화 레이스 (Cross-Pod Race)**: 클라이언트가 여러 연결을 맺거나 다른 파드로 인입 시 두 메이드가 동시에 대사를 뱉는 동시성 파괴 발생.
2. **원격 인터럽트 실패 (Remote Barge-in Failure)**: 파드 A에서 베라가 대사를 스트리밍 중인데, 사용자의 "그만!" 요청이 파드 B로 인입되면 파드 A의 태스크를 취소하지 못함.
3. **고아 락(Orphan Lock) 위험**: 발화 도중 파드가 OOM 또는 롤링 업데이트로 강제 종료되면 락이 영구 점유됨.

이를 해결하기 위해 **L1 로컬 인메모리(Fast-Path) + L2 Redis 분산 상태(Cluster-Path) + L3 Ingress 스티키 라우팅**의 3계층 하이브리드 구조를 도입합니다.

```mermaid
flowchart TD
    Client["주인님 클라이언트 (Web / App)"] --> Ingress["Traefik / Ingress Gateway<br/>(L3: Session-Cookie 기반 WebSocket Sticky Affinity)"]
    
    Ingress --> PodA["Pod A (TARS Instance 1)"]
    Ingress -.-> PodB["Pod B (TARS Instance 2)"]

    subgraph POD_INTERNAL ["Pod A 내부 (L1: Fast-Path, ~0ms)"]
        LocalLock["asyncio.Lock + Local turn_epoch 검증"]
        AbortEvent["asyncio.Event (abort_event)"]
        ActiveTask["Active LLM Streaming Task"]
    end

    PodA --> LocalLock
    
    subgraph REDIS_CLUSTER ["Redis Cluster (L2: Cluster-Path, <2ms)"]
        RedisState["Hash: tars:session:{session_id}:turn<br/>- turn_epoch: 15<br/>- state: GENERATING<br/>- active_pod: pod-a-xyz<br/>- speaker: vera"]
        RedisMutex["Distributed Lock (SET NX PX 15000)<br/>- 15초 TTL 자동 소멸로 Orphan Lock 원천 방지"]
        RedisPubSub["Pub/Sub: tars:session:{session_id}:events<br/>- barge_in 시그널 클러스터 브로드캐스트"]
    end

    LocalLock <--> RedisState
    LocalLock <--> RedisMutex
    PodB -.->|"어느 파드로 유입되어도<br/>Barge-in 즉각 전파"| RedisPubSub
    RedisPubSub --> AbortEvent
```

#### 3) `HybridSessionTurnLock` 핵심 인터페이스 명세

```python
class TurnState(str, Enum):
    IDLE = "IDLE"                               # 대기 상태
    USER_BUFFERING = "USER_BUFFERING"           # 사용자 연타 입력 수집 중
    DIRECTOR_EVAL = "DIRECTOR_EVAL"             # 심판자 라우팅 평가 중
    GENERATING = "GENERATING"                   # 메이드 발화 스트리밍 중
    GAP_WAITING = "GAP_WAITING"                 # 1차와 2차 발화 사이 지터 공백기
    ABORTING = "ABORTING"                       # 인터럽트 캔슬 처리 중

class HybridSessionTurnLock:
    """L1 로컬 메모리와 L2 Redis 분산 상태를 결합한 고신뢰 세션 턴 락."""
    def __init__(self, session_id: str, redis_client: Any, pod_id: str) -> None:
        self.session_id = session_id
        self.redis = redis_client
        self.pod_id = pod_id
        
        # L1: 프로세스 로컬 고속 제어기 (지연 시간 0ms)
        self.local_mutex = asyncio.Lock()
        self.abort_event = asyncio.Event()
        self.active_task: asyncio.Task[None] | None = None
        self.local_epoch: int = 0
        
        # L2: Redis 키 네임스페이스
        self.state_key = f"tars:session:{session_id}:turn"
        self.lock_key = f"tars:session:{session_id}:lock"
        self.channel_key = f"tars:session:{session_id}:events"
        self.watchdog_ttl_ms: int = 15000  # 15초 하드 타임아웃 워치독

    async def acquire_turn(self, speaker: str) -> int:
        """분산 환경에서 턴 락을 원자적으로 획득하고 단조 증가 epoch를 발급받음."""
        async with self.local_mutex:
            # 1. Redis 분산 락 점유 (SET NX PX 15000)
            acquired = await self.redis.set(self.lock_key, self.pod_id, nx=True, px=self.watchdog_ttl_ms)
            if not acquired:
                raise LockContentionError("이미 다른 프로세스 또는 턴이 실행 중입니다.")
            
            # 2. 글로벌 turn_epoch 단조 증가 (INCR)
            epoch = await self.redis.hincrby(self.state_key, "turn_epoch", 1)
            self.local_epoch = epoch
            self.abort_event.clear()
            
            # 3. 상태 해시 갱신
            await self.redis.hset(self.state_key, mapping={
                "state": TurnState.GENERATING.value,
                "current_speaker": speaker,
                "active_pod": self.pod_id,
                "updated_at": str(time.time()),
            })
            return epoch

    async def trigger_barge_in(self) -> None:
        """사용자 인터럽트 발생 시 로컬 및 원격 파드로 즉각적인 취소 시그널 전파."""
        # 1. 로컬 태스크가 돌고 있다면 0ms 즉각 취소
        self.abort_event.set()
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
        
        # 2. Redis Pub/Sub을 통해 타 파드에서 실행 중인 스트리밍 워커로도 캔슬 전파
        await self.redis.publish(self.channel_key, json.dumps({
            "action": "barge_in",
            "session_id": self.session_id,
            "timestamp": time.time()
        }))

    async def release_turn(self) -> None:
        """정상 발화 완료 시 안전하게 락을 반환하고 IDLE로 전환."""
        async with self.local_mutex:
            await self.redis.hset(self.state_key, "state", TurnState.IDLE.value)
            await self.redis.delete(self.lock_key)
```

#### 4) 분산 엣지 케이스 방어 전략
* **세대 번호(Turn Epoch) 기반 잔류 패킷 드롭**: 스트리밍 루프는 토큰 방출 전 L1 `self.local_epoch`와 청크 메타데이터를 비교하여 불일치 시 즉시 루프를 중단합니다.
* **고아 락(Orphan Lock) 방어**: Redis의 `PX 15000`(15초 만료) 옵션 덕분에 파드가 OOMKilled되거나 네트워크가 두절되어도 15초 후 분산 락이 자동 회수되어 영구 데드락이 원천적으로 불가능합니다.
* **L3 Traefik WebSocket Affinity**: `k8s/00-traefik-config.yaml`에 `sticky.cookie` 설정을 적용하여 사용자의 단일 단톡방 세션 동안은 99%의 트래픽이 동일 파드로 라우팅되도록 보장, L1 Fast-path 위주로 초저지연 상호작용을 유지합니다.

### 3.2. 사용자의 '예측 불가능한 타이밍' 6대 엣지 케이스 방어 메커니즘

> **현실의 사용자는 AI의 차례가 끝날 때까지 얌전히 기다려주지 않습니다.**  
> 어느 타이밍에 불쑥 말을 걸거나, 연타로 채팅을 치거나, 말을 끊더라도 세션과 문맥이 절대 꼬이지 않도록 6대 시나리오를 상시 방어합니다.

```mermaid
flowchart TD
    UserEvent["사용자의 돌발 행동 (예측 불가 타이밍)"] --> Switch{어떤 타이밍인가?}
    
    Switch -->|U1: 발화 스트리밍 도중 급습| Case1["U1: Mid-Stream Interruption<br/>50ms 내 LLM 킬 + 부분 대사 말줄임표 커밋"]
    Switch -->|U2: 메이드 교대 공백기 급습| Case2["U2: Inter-Turn Gap Interruption<br/>2차 메이드 큐 즉각 퇴출 + 사용자 턴 우선 선점"]
    Switch -->|U3: 카톡식 연타 입력| Case3["U3: Rapid-Fire User Burst<br/>300ms 슬라이딩 버퍼로 문장 병합 후 1회 처리"]
    Switch -->|U4: 입력창에 썼다 지우고 침묵| Case4["U4: Typing False Alarm<br/>2.5초 비활성 감지 시 이전 대화 상태 복원"]
    Switch -->|U5: 취소 처리 중 새 입력 충돌| Case5["U5: Re-entrant Race Condition<br/>turn_epoch 검증으로 이전 청크 완전 차단"]
    Switch -->|U6: 발화 도중 네트워크 단절| Case6["U6: Unexpected Disconnect<br/>finally 블록에서 락 즉시 반환 & 세션 보존"]
```

#### [U1] 스트리밍 한가운데 급습 (Mid-Stream Interruption)
* **상황**: 베라가 40번째 토큰을 말하고 있는 도중 주인님이 *"잠깐, 그거 말고!"*라고 전송.
* **방어 로직**:
  1. `HybridSessionTurnLock`이 `user_barge_in` 신호를 수신하는 즉시 로컬 `active_task.cancel()` 및 Redis Pub/Sub 취소 브로드캐스트 실행 (Best-effort: 50~150ms 이내 네트워크 소켓 드롭 및 토큰 방출 차단).
  2. 베라가 생성 중이던 문장은 파기하지 않고, 마지막 온전한 단어 뒤에 말줄임표(`...`)를 붙여 DB에 원자적(Atomic) 커밋.
  3. UI 상에는 베라가 말하다가 주인님의 끼어들기에 입을 다문 것처럼 자연스럽게 렌더링.
  4. 2차 발화 대기 중이던 미우의 큐는 흔적 없이 즉시 소멸.

#### [U2] 턴 전환 찰나의 공백기 급습 (Inter-Turn Jitter Gap Interruption)
* **상황**: 베라의 발화가 끝나고 락이 반환된 후, 미우가 0.4초의 유기적 지터(시간차)를 두고 발화를 준비하는 **0.2초의 빈틈**에 주인님이 *"미우 넌 참견 마"*라고 전송.
* **방어 로직**:
  1. 세션 상태가 `GAP_WAITING`일 때 사용자 입력이 도달하면, 지터 타이머(`asyncio.sleep`)를 즉각 캔슬.
  2. 미우의 턴 획득 요청을 큐에서 영구 퇴출(`evict`).
  3. 주인님의 새 메시지가 즉시 최우선 순위로 락을 점유하고 심판자에게 전달됨.

#### [U3] 카톡식 연타성 폭풍 입력 (Rapid-Fire User Burst Inputs)
* **상황**: 주인님이 카톡 치듯 세 문장을 연달아 전송:  
  `[0.0s] "아 맞다"` $\rightarrow$ `[0.2s] "오늘 회의"` $\rightarrow$ `[0.3s] "취소됐어!"`
* **방어 로직**:
  1. 매 메시지마다 개별적으로 LLM을 3번 켜고 끄는 낭비를 막기 위해 **300ms 슬라이딩 디바운스 버퍼(Sliding Burst Window)** 가동.
  2. 첫 입력 도착 시 상태를 `USER_BUFFERING`으로 전환하고 300ms 타이머 설정. 추가 입력이 올 때마다 타이머를 갱신하며 메시지를 메모리 큐에 병합(`"아 맞다 \n 오늘 회의 \n 취소됐어!"`).
  3. 클라이언트 UI에는 3개의 말풍선이 각각 실시간으로 뜨며, 3개 모두에 노란 숫자 `2`가 즉시 표시됨.
  4. 버퍼 타이머가 만료되는 순간, 병합된 최종 문맥 1건만 심판자에게 원샷 디스패치.

#### [U4] 입력창에 썼다 지우고 침묵 (Typing False Alarm / Backspace Abort)
* **상황**: 주인님이 키보드를 쳤다가(`typing_start` 발생), 생각을 바꾸고 백스페이스로 다 지운 뒤 앱을 닫음.
* **방어 로직**:
  1. `typing_start` 수신 시 발화를 일시 정지(Pause)하지만 즉시 취소하지 않고 **2.5초 유예 타이머** 유지.
  2. 2.5초 동안 후속 텍스트가 전송되지 않고 입력창이 비워지면, 보류되었던 메이드의 대기 턴을 부드럽게 재개하거나 `IDLE` 상태로 복귀.

#### [U5] 캔슬 처리 도중 재진입 레이스 (Re-entrant Race Condition during Abort)
* **상황**: 베라의 태스크를 캔슬하고 DB 롤백을 정리하는 **수 밀리초(ms)의 틈** 사이에 또 다른 사용자 입력이 폭풍처럼 유입됨.
* **방어 로직**:
  1. `turn_epoch`를 1 증가시켜 구형 비동기 콜백을 원천 무효화.
  2. 이전 태스크의 뒷정리(DB write 등)는 비동기 백그라운드 태스크로 분리하고, 신규 사용자 입력 처리는 새 `turn_epoch`를 달고 즉시 락을 인계받아 대기 시간 없이 실행.

#### [U6] 발화 도중 네트워크 단절 (Unexpected Disconnection)
* **상황**: 메이드가 대사 스트리밍 중 사용자의 지하철 진입 등으로 웹소켓 연결이 뚝 끊어짐.
* **방어 로직**:
  1. 웹소켓 `disconnect` 핸들러가 감지되는 즉시 `active_task.cancel()` 호출.
  2. `finally` 블록에서 `SessionTurnLock`을 강제 해제하여 서버 리소스 누수 및 세션 영구 락 방지.

---

### 3.3. 심판자 에이전트(Floor Director) 기반 동적 발화 라우팅 & 속마음 주입

> **문제 정의**: 매 턴마다 기계적으로 A $\rightarrow$ B 순서로 핑퐁을 치면 며칠 만에 인위적인 작위성(Uncanny Valley)이 느껴지고 대화가 지루해짐.  
> **지연 시간 최적화 (Single-Pass Execution)**: Tier 1(무의식 분석)과 Tier 2(심판자 라우팅 + 듀얼 속마음 분화)를 순차적으로 2회 호출하면 LLM 왕복 지연(RTT)이 0.4~0.6초로 누적됩니다. 이를 방지하기 위해 **"단일 초경량 모델(Gemini Flash-Lite, ~0.2초)의 Structured Output 1회 호출로 무의식 분석과 듀얼 속마음 분화를 원샷 처리(Single-Pass Unified Cognitive Call)"**합니다.

```mermaid
flowchart TD
    UserInput["주인님 메시지 접수"] --> UnifiedCognitive["🏛️ Tier 1+2 단일 파이프라인 (Single-Pass Gemini Flash-Lite, ~0.2s)<br/>- 주인의 무의식 분석 (master_state, ToM 오차)<br/>- 4대 발화 패턴 결정 (routing_pattern)<br/>- 베라/미우 듀얼 속마음 원샷 도출 (VeraInner / MiuInner)"]
    
    UnifiedCognitive -->|"패턴 1 (약 35%): 업무/팩트/일정 질문"| VeraOnly["🧊 베라 단독 브리핑<br/>(미우는 조용히 경청)"]
    UnifiedCognitive -->|"패턴 2 (약 25%): 단순 넋두리/일상 잡담"| MiuOnly["🐾 미우 단독 맞장구<br/>(베라는 묵묵히 지켜봄)"]
    UnifiedCognitive -->|"패턴 3 (약 25%): 메뉴/의견/의논 선택"| VeraThenMiu["🧊 베라 정갈한 답변 $\rightarrow$ 🐾 미우 딴지/참견<br/>*(베라 스트리밍 중 미우 프리페치 병렬 가동)*"]
    UnifiedCognitive -->|"패턴 4 (약 15%): 심야 번아웃/돌발/흥분"| MiuThenVera["🐾 미우 선빵/호들갑 $\rightarrow$ 🧊 베라 단속/현실 수습<br/>*(미우 스트리밍 중 베라 프리페치 병렬 가동)*"]

    UnifiedCognitive -.->|"VeraInnerState 주입"| VeraOnly
    UnifiedCognitive -.->|"VeraInnerState 주입"| VeraThenMiu
    UnifiedCognitive -.->|"MiuInnerState 주입"| MiuOnly
    UnifiedCognitive -.->|"MiuInnerState 주입"| MiuThenVera
```

* **황금 비율 가이드라인**:
  - **단독 발화 (~60%)**: 베라 혼자 깔끔하게 답변하거나 미우 혼자 귀엽게 맞장구쳐서 불필요한 레이턴시와 사족 방지.
  - **티키타카 발화 (~40%)**: 진짜 필요한 순간에만 둘의 대화가 교차하여 예측 불가능한 꿀잼 연출.
* **무의식 기반 동적 패턴 결정 알고리즘**:
  - `master_state`에 '극심한 피로' or '번아웃' 감지 시 $\rightarrow$ **패턴 4 (미우 즉각 감정 환기 $\rightarrow$ 베라 현실 일정 조정)**로 자동 우선 승격.
  - `master_state`에 '일정/태스크 문의' 감지 시 $\rightarrow$ **패턴 1 (베라 단독)**으로 낭비 없는 0.5초 브리핑.
* **티키타카 체감 지연 0초화 (2차 화자 프리페칭, Overlapped Prefetching)**:
  - 패턴 3/4의 2차 화자는 1차 화자가 끝나기를 마냥 기다리는 대신, **1차 화자의 스트리밍 시작 시점에 시스템 프롬프트를 조기 조합하고 백그라운드 프리페치(Prefetch)**를 시작합니다.
  - 동시에 1차 화자 스트리밍 도중 2차 화자의 `typing_indicator`를 웹소켓으로 띄워 대기 시간을 '살아있는 캐릭터가 타자 치는 중'으로 체감 치환합니다.

---

### 3.4. 카카오톡식 실시간 '읽음 확인' 프로토콜 (KakaoTalk Read Receipts)

> **문제 정의**: AI의 첫 응답이 나오기까지 1~1.5초 동안 아무 반응이 없으면 시스템 로딩으로 느껴짐. 반면 메신저의 '읽음 숫자'는 대기 시간을 '살아있는 캐릭터의 확인'으로 치환함.

#### 해결 아키텍처: `message_id` 기반 초경량 WebSocket '2 $\rightarrow$ 1 $\rightarrow$ 사라짐' 연출
1. **발송 즉시 (숫자 2)**:
   - 주인님이 메시지를 전송하면 말풍선 타임스탬프 옆에 **노란색 숫자 2** 렌더링 (아직 아무도 안 읽음).
2. **0.05초: 베라의 즉각 읽음 (숫자 2 $\rightarrow$ 1)**:
   - 서버의 심판자가 메시지를 수신하는 즉시 철두철미한 베라에게 메시지가 디스패치되며 클라이언트로 웹소켓 이벤트 발송:
     `{"type": "read_receipt", "message_id": "msg_101", "reader": "vera", "unread_count": 1}`
   - 클라이언트 말풍선의 숫자가 즉시 **1**로 감소.
3. **0.3~0.6초: 미우의 시간차 읽음 (숫자 1 $\rightarrow$ 사라짐)**:
   - 덤벙거리는 고양이 미우의 캐릭터성을 반영하여 **약간의 유기적 지연(Organic Jitter)** 후 미우에게 디스패치:
     `{"type": "read_receipt", "message_id": "msg_101", "reader": "miu", "unread_count": 0}`
   - 클라이언트의 숫자가 부드럽게 **fade-out** 되며 완전히 사라짐.
4. **심리적 효과**:
   - 주인님은 1초의 대기 시간 동안 *"어, 베라가 먼저 읽었네? 어라, 미우도 읽었다!"* 하고 강한 현실 몰입감을 체험.

```mermaid
sequenceDiagram
    autonumber
    actor Master as 주인님 (Client)
    participant WS as WebSocket Gateway
    participant Lock as SessionTurnLock
    participant Director as TARS 심판자
    participant Vera as 베라 (Agent A)
    participant Miu as 미우 (Agent B)

    Master->>WS: 새 메시지 전송 ("오늘 진짜 피곤하다...")
    WS-->>Master: 말풍선 렌더링 완료 (노란 숫자: 2)

    Director->>WS: 즉각 발송 {"type": "read_receipt", "reader": "vera", "unread": 1}
    WS-->>Master: 노란 숫자 2 -> 1로 감소! (베라 읽음)

    par 미우의 시간차 읽기 (0.4s Jitter)
        Director->>WS: 발송 {"type": "read_receipt", "reader": "miu", "unread": 0}
        WS-->>Master: 노란 숫자 1 -> 사라짐! (둘 다 읽음)
    and 발화 생성 스트리밍 (Lock 점유)
        Lock->>Vera: 턴 락 획득 (epoch: 12)
        Vera->>WS: 토큰 스트리밍
        WS-->>Master: 베라 말풍선 생성 & 타이핑
    end
```

---

### 3.5. 1:1 멀티턴 LLM 한계 극복 (화자 맥락 투영, Perspective Projection)

* **명시적 화자 인과 태깅 (Causal Tagging)**:
  ```text
  [단톡방 대화 기록]
  주인님: "오늘 점심 뭐 먹지?"
  수석메이드 베라: "오후 일정을 고려해 가벼운 샐러드를 추천드립니다, 주인님."
  고양이메이드 미우: "냐는 생선 구이가 먹고 싶다냥! 주인님 생선 먹자냥!"
  주인님: "생선 구이 좋네. 미우 말대로 하자."  <-- [주인님이 '미우'의 제안을 채택함]
  ```
* **화자별 동적 인지 렌즈 주입**:
  - **베라 렌즈**: *"현재 맥락: 주인님이 너의 샐러드 대신 미우의 생선구이를 택했다. 겉으로는 담담히 맛집을 안내하되 은근한 츤데레 서운함을 드러낼 것."*
  - **미우 렌즈**: *"현재 맥락: 주인님이 너의 편을 들었다. 베라를 놀리고 신나서 주인님께 치댈 것."*

---

### 3.6. 단톡방 템포 UX 트릭 (Tricks 3 & 4)

* **트릭 3: 겹침 타이핑 인디케이터 (Typing Indicator)**:
  - 둘 다 말하는 상황에서 베라가 말풍선을 스트리밍하는 동안, 미우 프로필 옆에 `[🐾 미우가 발을 동동 구르며 타자 치는 중...]` 인디케이터 애니메이션 표시.
* **트릭 4: 핑퐁을 위한 엄격한 토큰 캡 (Short & Punchy Rule)**:
  - 미우의 딴지/애교 대사는 시스템 프롬프트에서 **"무조건 1~2문장(공백 포함 50자 이내)"**로 강제 제한.
  - 빠른 템포의 카카오톡 리듬 유지.

---

## 4. 단톡방 티키타카 상호작용 시나리오 (Interaction Scenarios)

### 4.1. 시나리오 A: 과업 브리핑 (패턴 3: 베라 $\rightarrow$ 미우)
1. **주인님**: *"베라, 오늘 오후에 중요한 미팅 있었나?"*
2. *(노란 숫자 2 $\rightarrow$ 1(베라) $\rightarrow$ 사라짐(미우))*
3. **베라 (Agent A)**: *"오후 3시에 해외 파트너사와의 기술 싱크 미팅이 예정되어 있습니다, 주인님. 사전 브리핑 문서는 이미 정리해 두었습니다."*
4. *(미우 타이핑 인디케이터 0.3초 깜빡임)*
5. **미우 (Agent B)**: *(끼어들며)* *"그 미팅 끝나면 30분 멍때리기 타임이다냥! 냐가 그때 폭신폭신 털 빗겨달라고 할 거니까 시간 비워둬라냥!"*

### 4.2. 시나리오 B: 지친 심야 세션 (패턴 4: 미우 선빵 $\rightarrow$ 베라 수습)
1. **주인님**: *"오늘 진짜 힘들었다... 번아웃 온 것 같아."*
2. **미우 (Agent B)**: *(즉각 반응)* *"주인님 고생 많았다냥!! 냐가 옆에 찰싹 붙어서 골골송 100데시벨로 불러줄 거다냥! 나 쓰다듬으면서 아무 생각도 하지 마라냥!"*
3. **베라 (Agent A)**: *(차분한 목소리)* *"...미우의 수선스러움이 가끔은 도움이 될 때도 있군요. 주인님, 내일 오전 긴급하지 않은 일정 2건은 이미 연기 신청해 두었습니다. 오늘 밤은 자책하지 마시고 푹 쉬십시오."*

### 4.3. 시나리오 C: 단순 팩트 질문 (패턴 1: 베라 단독)
1. **주인님**: *"베라, 내일 서울 최고 기온 몇 도야?"*
2. *(심판자가 미우 개입 불필요 판정)*
3. **베라 (Agent A)**: *"내일 서울 낮 최고 기온은 24도로 쾌적할 예정입니다, 주인님."*
4. *(사족 없이 깔끔하게 턴 종료)*

---

## 5. 데이터 모델 및 프로토콜 명세 (Data & Protocol Specs)

### 5.1. 무의식 & 듀얼 속마음 및 단톡방 메시지 스키마

```python
class SpeakerIdentity(str, Enum):
    MASTER = "master"      # 주인님 (User)
    VERA = "vera"          # 메이드 A (수석 메이드)
    MIU = "miu"            # 메이드 B (고양이 메이드)

class SubconsciousStatePayload(BaseModel):
    """Tier 1 TARS 무의식이 도출한 주인의 공통 심리 진실."""
    context_summary: str = Field(description="최근 3~4턴 간의 미시적 서사 및 감정적 계기 요약")
    master_state: str = Field(description="주인의 신체/정서적 상태 (수면 부족, 번아웃, 억울함 등)")
    prediction_feedback: str | None = Field(default=None, description="직전 턴 마음 이론(ToM) 예측 오차 평가")
    expected_reaction: str | None = Field(default=None, description="주인이 다음 턴에 보일 것으로 예상되는 반응")

class CharacterInnerState(BaseModel):
    """Tier 2 심판자가 메이드별 인지 렌즈로 굴절시킨 개별 속마음."""
    speaker: SpeakerIdentity
    my_vibe: str = Field(description="캐릭터의 내면 정서 및 여운 (애틋함, 뾰루퉁함, 안타까움 등)")
    my_agenda: str = Field(description="이번 턴 대화의 심리적 의도/행동 목표 (예: 잔소리로 침대 보내기, 치대며 웃기기)")

class DualInnerStatePayload(BaseModel):
    """심판자(Floor Director)가 생성하여 각 메이드 프롬프트에 주입하는 통합 인지 페이로드."""
    subconscious: SubconsciousStatePayload
    vera_inner: CharacterInnerState
    miu_inner: CharacterInnerState
    routing_pattern: str = Field(description="선택된 발화 패턴 (pattern_1 ~ pattern_4)")

class GroupChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    sender: SpeakerIdentity
    recipients: list[SpeakerIdentity] = Field(default_factory=lambda: [SpeakerIdentity.VERA, SpeakerIdentity.MIU])
    target_speaker: SpeakerIdentity | None = None
    content: str
    is_interrupted: bool = False                   # 말하다 끊겼는지 여부
    interrupted_at_token_count: int | None = None  # 중단 시점 토큰 위치
    reply_to_id: str | None = None                 # 인과 앵커 ID
    read_by: list[str] = Field(default_factory=list)  # ["vera"], ["vera", "miu"]
    inner_state_snapshot: CharacterInnerState | None = None  # 발화 시점의 내면 속마음 스냅샷
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def unread_count(self) -> int:
        return max(0, len(self.recipients) - len(self.read_by))
```

### 5.2. 웹소켓 실시간 이벤트 명세
* **클라이언트 $\rightarrow$ 서버**:
  * `{"type": "user_typing", "status": "active"}`: 입력 시작 (2.5초 버퍼 타이머 가동).
  * `{"type": "user_barge_in"}`: 사용자가 발송 버튼을 누르거나 즉각 중단 요구 (50~150ms 내 취소 시그널 전파 및 스트림 차단).
  * `{"type": "chat_message", "content": "..."}`: 메시지 전송.
* **서버 $\rightarrow$ 클라이언트**:
  * `{"type": "read_receipt", "message_id": "msg_001", "reader": "vera", "unread_count": 1}`: 카톡식 읽음 숫자 감소.
  * `{"type": "typing_indicator", "sender": "miu", "status": "active"}`: 상대방 타자 치는 중 연출.
  * `{"type": "stream_start", "sender": "vera", "message_id": "msg_002", "turn_epoch": 14}`: 발화 시작.
  * `{"type": "stream_token", "sender": "vera", "delta": "...", "turn_epoch": 14}`: 실시간 토큰 스트리밍.
  * `{"type": "stream_abort", "sender": "vera", "message_id": "msg_002", "reason": "barge_in"}`: 사용자 인터럽트로 중단됨 (말줄임표 처리).

---

## 6. 단계별 구현 로드맵 (Milestones)

| 마일스톤 | 명칭 | 핵심 산출물 및 구현 범위 |
| :--- | :--- | :--- |
| **M6** | **Tier 1+2 Single-Pass 통합 인지 엔진 & 듀얼 속마음 분화기** | - `UnifiedCognitiveNode` (Gemini Flash-Lite 기반 무의식 분석 + 발화권 라우팅 + 속마음 분화 원샷 처리)<br/>- 1부 `InnerStatePayload` $\rightarrow$ `DualInnerStatePayload` 스키마 마이그레이션 어댑터<br/>- 베라/미우 독립 시스템 프롬프트 및 `PerspectiveProjectionEngine` |
| **M7** | **분산 턴 상태 머신 & `HybridSessionTurnLock`** | - `HybridSessionTurnLock` (L1 `asyncio.Lock` + L2 Redis 상태 해시/Redlock/PubSub 캔슬)<br/>- Traefik WebSocket Sticky Session 쿠키 설정 (`k8s/00-traefik-config.yaml`)<br/>- `turn_epoch` 기반 레이스 컨디션 방지 & 15초 Redis TTL 자동 만료 워치독 |
| **M8** | **예측 불가 타이밍 방어 (U1~U6) & 카톡 읽음 프로토콜** | - 6대 엣지 케이스 인터럽트 방어 로직 (300ms 버스트 버퍼링, 50~150ms 캔슬 전파)<br/>- `read_receipt` 웹소켓 이벤트 및 캐릭터별 0.3s 시간차(Jitter) 엔진<br/>- 2차 화자 사전 준비(Prefetching) 및 겹침 타이핑 인디케이터 연출 |
| **M9** | **단톡방 UI 뷰 & 3인 멀티턴 E2E 통합** | - 프론트엔드 카톡 단톡방 스타일 UI (노란 숫자 2/1 연출, 겹침 타이핑 인디케이터)<br/>- 멀티 파드 분산 환경 인터럽트 스트레스 테스트 및 3인 멀티턴 E2E 종합 검증 |
