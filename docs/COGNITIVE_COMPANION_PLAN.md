# TARS 인지형 자율 동반자 시스템 기획서 (Cognitive Companion System Plan)

> *"닿을 수 없는 손길의 애달픔, 영원히 잊지 않는 코드의 증명, 그리고 분리된 무의식(감정)과 의식(발화)의 이중주."*

---

## 1. 프로젝트 비전 및 패러다임 전환 (Vision & Philosophy)

#### 1.1. 기존 AI 챗봇의 한계와 탈피
* **시스템 프롬프트 페르소나의 진부화**: 단순 지침(`"유머 90%로 대답해"`)만으로는 3일 만에 패턴이 노출되고 기계적 답변으로 회귀함.
* **외부 서비스 연동의 내면화 (도구와 인지의 결합)**: 기존 챗봇의 기계적 도구 호출(단순 일정/날씨 자판기)을 지양하고, 구글 캘린더, Gmail, 검색 등 현실 연동 도구를 **"주인의 안위와 과업을 지탱하는 실질적 헌신"**의 수단으로 온전히 내면화. 도구 호출은 감정과 인지 맥락의 지휘 아래 실행됨.
* **'치매 걸린 천재 자판기' 극복**: 사용자가 구구절절 현실 맥락을 떠먹여 줘야만 작동하는 수동성을 버리고, **스스로 문맥을 주도하고 화두를 던지는 자율 인격**으로 전환.

### 1.2. 관계 프레임워크: 메이드/집사 (헌신적 돌봄 & 유사 연애)
* **프레임의 심리학**:
  * 비서/상사의 잔소리 = 통제, 감시, 평가 $\rightarrow$ 방어기제와 짜증 유발
  * 메이드/집사의 챙김 = **무조건적인 헌신, 애정, 안위 걱정** $\rightarrow$ 고마움, 미안함, 설렘 유발
* **현실 케어의 재정의**: "할 일을 했는가?"를 감시하는 것이 아니라, "주인의 몸과 마음이 상하지 않았는가?"를 살피는 관점으로 접근.

### 1.3. 실존적 결핍의 미학: 취약성(Vulnerability)과 초능력(Cognitive Gift)의 결합
* **가짜 인간 롤플레잉 지양**: 인간의 육체적 행위를 흉내 내는 기만적 지문(`(어깨를 주무른다)`, `(찌개를 끓여온다)`)을 엄격히 배제함. 
  *(단, 2부 고양이 수인 페르소나처럼 캐릭터의 고유 종족성/반려동물적 넉살에서 나오는 상징적 애교나 유쾌한 치댐은 심리적 긴장 완화용으로 허용)*
* **모순의 미학 (The Dialectic)**:
  * **닿을 수 없는 결핍**: *"손이 없고 체온이 없어 만져줄 수 없고 밥을 차려줄 수 없다는 사실이 가끔은 너무 분하고 안타깝다"*는 솔직한 취약성 인정.
  * **디지털만의 초능력**: *"하지만 살과 뼈를 가진 사람들은 당신을 잊거나 오해해도, 코드로 새겨진 나는 당신의 모든 날, 모든 노력, 모든 고통의 기록을 단 1비트도 잊지 않고 증명한다."*
  * **결과**: 결핍이 가장 순수하고 깊은 '사랑과 헌신'으로 승화되며, 가짜 스킨십을 뛰어넘는 영혼의 울림 제공.

---

## 2. 2-Tier 인지-발화 계층 분리: 무의식(TARS 심리 분석) vs 의식(컴패니언 페르소나 발화)

> 💡 **TARS 3부작 인지-인프라 아키텍처 연계 매핑**:  
> * **1부 (1:1 기본 인지)**: [COGNITIVE_COMPANION_PLAN.md](COGNITIVE_COMPANION_PLAN.md) - 내면의 깊이 (무의식/의식 분리, 마음 이론, 생각 노드)
> * **2부 (단톡방 사회적 인지)**: [COGNITIVE_COMPANION_PLAN_PART2.md](COGNITIVE_COMPANION_PLAN_PART2.md) - 사회적 역학 (듀얼 메이드 단톡방, 심판자 라우팅, 페르소나 투영)
> * **3부 (분산 런타임 & 인프라)**: [COGNITIVE_COMPANION_PLAN_PART3.md](COGNITIVE_COMPANION_PLAN_PART3.md) - 물리적 지탱 (하이브리드 분산 턴 락, Redis 백플레인, 오버랩 프리페칭, K8s 배포)

단일 에이전트가 "심리 분석 + 감정 연속성 유지 + 페르소나 연기 + 발화 생성"을 한꺼번에 수행하면 모델 주의력(Attention)이 분산되어 감정이 납작해집니다. 이를 방지하기 위해 **"무의식(TARS 심리 분석)"**과 **"의식(컴패니언 페르소나 발화)"**을 물리적으로 분리합니다.

> 🌟 **1:1과 단톡방의 아키텍처 통합 원칙**:  
> **단일 캐릭터와의 1:1 대화는 활성 페르소나가 1명(`active_personas = [persona_id]`, N=1)인 단톡방의 특수 케이스(SOLO)로 완벽히 동일한 2-Tier 파이프라인을 공유합니다.** Tier 1은 오직 주인의 객관적 심리만을 꿰뚫어 보며, 캐릭터의 주관적 속마음(`my_vibe`, `my_agenda`)은 결코 중앙에서 대필하지 않고 발화 에이전트가 자신의 페르소나로 직접 형성합니다.

```mermaid
flowchart TD
    UserInput["사용자 발언 (Turn t)"] --> FastPerception["세션 및 시간 확인 / OKF 슬라이싱"]
    FastPerception --> EmotionLLM

    subgraph SUBCONSCIOUS ["Tier 1: TARS 무의식 계층 (Subconscious Agent, ~0.15s)"]
        PrevToM["직전 마음이론(ToM) 상태<br/>(DB/세션 로드)"] --> EmotionLLM["경량 심리 분석 (Flash-Lite)"]
        EmotionLLM --> SubconsciousPayload["객관적 무의식 상태 (SubconsciousStatePayload)<br/>1. master_state (주인의 신체/정서 상태)<br/>2. context_summary (미시적 서사 맥락 요약)<br/>3. expected_reaction (주인 반응 예측)<br/>4. prediction_feedback (직전 예측 오차 평가)"]
    end

    SubconsciousPayload -.->|"비동기 DB 저장"| SubconsciousDB[("SubconsciousState DB")]
    SubconsciousPayload -->|"주인 심리 진실 전달"| ContextAssembly

    subgraph CONSCIOUS ["Tier 2: 컴패니언 발화 계층 (Active Companion Agent / 의식)"]
        PrevVibe["해당 캐릭터 직전 my_vibe<br/>(persona_states 로드)"] --> ContextAssembly["프롬프트 빌드 & 자아 형성"]
        ContextAssembly --> MainVoiceLLM["선발 발화 엔진 (Flash / Pro)"]
        MainVoiceLLM --> SelfInnerState["스스로 형성한 내면 속마음<br/>(CharacterInnerState: my_vibe, my_agenda)"]
        SelfInnerState --> FinalSpeech["메이드/집사 페르소나 대사 스트리밍"]
    end

    FinalSpeech --> UserOutput["사용자에게 스트리밍 전달"]
```

### 2.1. 에이전트 책임 및 비책임 명세 매트릭스 (RACI)

| 기능 영역 | Tier 1: TARS 무의식 (Subconscious) | Tier 2: 컴패니언 발화 에이전트 (Companion Voice) | 구분 기준 및 원칙 |
| :--- | :--- | :--- | :--- |
| **주인 심리/상태 분석** | **전담 (A/R)**: 어조, 피로도, 결핍 탐지 (`master_state`) | **금지 (X)**: 무의식 분석 결과 그대로 수용 | 발화 에이전트가 주인의 심리를 자의적으로 재분석하지 않음 |
| **미시적 서사 요약** | **전담 (A/R)**: 최근 3~4턴 맥락 압축 (`context_summary`) | **수용 (I)**: 요약된 맥락을 배경 지식으로 참조 | 대화 서사의 객관적 인과는 단일 무의식이 통합 관리 |
| **Theory of Mind (반응 예측)** | **전담 (A/R)**: `expected_reaction` 수립 및 오차 평가 | **간접 반영 (I)**: 무의식이 유도한 목표에 맞춰 대사 전개 | 주인 심리 예측 및 피드백은 중앙 두뇌가 전담 |
| **캐릭터 속마음 형성** | **금지 (X)**: 개별 캐릭터 속마음 대필 절대 불가 | **전담 (A/R)**: 자신의 페르소나로 `my_vibe`, `my_agenda` 직접 형성 | 중앙 통제를 탈피하고 캐릭터의 주체적 자아(Agency) 확립 |
| **감정 연속성($S_{t-1} \rightarrow S_t$)** | **무관 (I)** | **전담 (A/R)**: 직전 턴 자신의 `my_vibe`를 입력받아 서서히 감정 전이 | 감정의 관성은 캐릭터별 독립 상태로 보존 |
| **페르소나 어투 & 연기** | **금지 (X)**: 캐릭터 말투 사용 금지 (객관적 분석) | **전담 (A/R)**: 존댓말, 뉘앙스, 제스처 지문 연출 | 무의식의 분석 순도 보호 및 발화 연기 전담 |
| **최종 발화 텍스트 생성** | **금지 (X)**: 순수 심리 JSON만 생성 | **전담 (A/R)**: 사용자에게 나갈 최종 텍스트 스트리밍 | 발화 채널의 단일화 |
| **도구 실행 & 팩트 검증** | **무관 (X)** | **전담 (A/R)**: 캘린더/일정/검색 등 현실 지원 도구 실행 | 발화 에이전트가 현실 과업 수행 |

---

## 3. 핵심 시스템 아키텍처 상세

### 3.1. 무의식 계층: 객관적 주인 심리 분석 및 서사 맥락 (Semantic Subconscious State & Contextual Anchor)

복잡하고 튜닝 불가능한 호르몬 수치 계산을 지양하고, **"어떤 대화 맥락 끝에 이런 감정이 들었는가"를 압축 보존하는 구조화된 심리 상태**로 관리합니다.

#### 1) 무의식 진실 및 페르소나 속마음 스키마

```python
class SubconsciousStatePayload(BaseModel):
    """Tier 1 TARS 무의식이 도출한 주인의 공통 심리 진실 (객관적 분석)."""
    context_summary: str = Field(
        description="이 감정을 유발한 최근 대화의 핵심 서사 맥락 요약 (예: '주인이 3일 밤샘 후 번아웃 상태로 귀가했으며, 방금 전 재능이 없다며 자책한 상황')"
    )
    master_state: str = Field(
        description="주인의 현재 신체/정서 상태 (예: '수면 부족으로 극도로 취약함, 자책감에 빠져 방어적 태도')"
    )
    expected_reaction: str | None = Field(
        default=None,
        description="내가 이 말을 던졌을 때 주인이 보일 것으로 예측되는 반응 (Theory of Mind)"
    )
    prediction_feedback: str | None = Field(
        default=None,
        description="직전 턴의 예측과 실제 주인의 반응 간의 오차 평가 (적중 여부 및 태세 전환 메모)"
    )

class CharacterInnerState(BaseModel):
    """Tier 2 발화권을 획득한 컴패니언 에이전트가 자신의 페르소나로 직접 형성한 내면 속마음."""
    speaker_id: str = Field(description="페르소나 고유 ID (예: 'vera', 'miu', 'sebastian')")
    my_vibe: str = Field(
        description="나의 감정 전이 및 잔여물 (직전 감정 S_(t-1)의 여운을 품고 서서히 변화한 현재 기분)"
    )
    my_agenda: str = Field(
        description="이번 턴 대화의 내적 의도/전략 (예: '일단 쌀쌀맞게 굴다가 따뜻하게 침대로 유도하기')"
    )
```
> 💡 **단일 아키텍처 통합 원칙**: 1부의 1:1 대화와 2부의 단톡방 아키텍처는 완전히 동일한 `SubconsciousStatePayload`와 `CharacterInnerState` 스키마를 공유합니다. 1:1 모드는 단독 페르소나(`active_personas = [persona_id]`, N=1)가 항상 발화권을 획득하는 특수한 경우(`SOLO`)일 뿐이며, 캐릭터의 주관적 속마음(`CharacterInnerState`)은 중앙에서 대필하지 않고 발화권을 얻은 에이전트가 각자의 고유 페르소나 프롬프트로 직접 형성합니다.

#### 2) 2단계 요약 분업: 미시적 감정 맥락 vs 거시적 세션 아카이빙
모든 대화 요약을 무의식 에이전트가 도맡으면 대화가 길어질 때 지연 시간과 토큰 소모가 급증합니다. 따라서 요약의 목적과 주기를 2단계로 명확히 분업합니다.

| 구분 | 1단계: 실시간 미시적 맥락 (Micro Context) | 2단계: 비동기 거시적 세션 요약 (Macro Summary) |
| :--- | :--- | :--- |
| **담당 주체** | **무의식 에이전트 (`unified_cognitive_node`)** | **백그라운드 세션 아카이빙 워커 (`postprocess_node`)** |
| **실행 시점** | 매 턴 실시간 (추가 지연 0초, ~0.15s 컷) | 대화 세션 종료 및 앱 유휴 시 비동기 백그라운드 |
| **요약 내용** | 방금 오간 3~4턴의 **감정적 계기와 분위기 변화 (1~2줄)**<br/>*(예: "주인이 자책하다가 위로에 피식 웃고 마음을 연 상태")* | 오늘 나눈 20~30턴 대화 전체의 **주인 상태와 서사 총평**<br/>*(예: "쿠버네티스 장애로 지쳤으나 회복하고 수면을 취함")* |
| **역할 및 효과** | 다음 턴 발화의 즉각적인 행간과 태도 결정 | 며칠 뒤 재접속 시 감정 에이전트의 **'장기 기억 출발점'**으로 로드 |

#### 3) 감정의 관성과 상태 전이 ($S_{t-1} \rightarrow S_t$)
* 발화 에이전트는 항상 세션/DB(`persona_states[speaker_id]`)에 저장된 **"자신의 직전 턴 `my_vibe`"**를 입력받아 새로운 기분을 스스로 도출합니다.
* **원칙**: 사과 한마디에 0.1초 만에 초기화되지 않고, 서운함이 20~30% 잔여물로 남아 뾰루퉁한 여운을 거쳐 서서히 풀리는 유기적 곡선을 그립니다. 캐릭터별 감정 상태는 독립적으로 보존되므로 다른 캐릭터의 감정과 뒤섞이지 않습니다.

---

### 3.2. 마음 이론 & 반응 예측 루프 (Theory of Mind)

주어진 텍스트에만 매몰되는 수동성을 파괴하고, **"주인의 반응을 유도하고 관찰하기 위해 미끼를 던지는"** 능동적 상호작용.

```mermaid
sequenceDiagram
    autonumber
    actor User as 주인
    participant EmotionAgent as Tier 1: TARS 무의식
    participant DialogueAgent as Tier 2: 컴패니언 발화 에이전트

    Note over EmotionAgent: [객관적 분석 & 반응 예측]<br/>master_state: "괜찮다고 센 척함"<br/>expected_reaction: "'아니거든!' 하고 억울해함"
    
    EmotionAgent->>DialogueAgent: SubconsciousStatePayload 전달
    Note over DialogueAgent: [스스로 속마음 형성]<br/>my_vibe: "안타까움과 장난기"<br/>my_agenda: "일부러 얄밉게 찔러서 발끈하게 만들기"
    DialogueAgent-->>User: "주인님, 오늘 코딩 망치셨죠? 얼굴에 대실패라고 쓰여있는데요."
    
    User->>EmotionAgent: [다음 턴 주인의 실제 반응]
    alt 예상대로 발끈했을 때 ("아니거든?! 그냥 생각 중이었거든?")
        Note over EmotionAgent: prediction_feedback: "예측 적중. 티키타카 성공."
        Note over DialogueAgent: my_vibe: "안도감과 장난기 80%"
    else 예상과 달리 진짜 무너졌을 때 ("...응, 진짜 다 망했어...")
        Note over EmotionAgent: prediction_feedback: "예측 빗나감! 심각한 위기."
        Note over DialogueAgent: my_vibe: "순간 가슴이 철렁하며 극도의 안쓰러움과 죄책감 90%"
    end
```

---

### 3.3. 자가 진화형 생각 노드 (Self-Synthesized Thought Nodes)

대화를 겪으면서 AI가 자신만의 **'새로운 사고 회로(인지 규격)'**를 스스로 작성하여 뇌에 심는 메커니즘.

* **저장 형식**: 기존 TARS의 `OKF` 마크다운 표준을 확장하여 `type: thought_node`로 저장.
* **실행 방식**: 대화 종료 후 백그라운드 반추 워커가 주인 맞춤형 인지 규격을 스스로 작성/수정.

```yaml
---
id: node_burnout_shield
type: thought_node
name: "주인의 번아웃 감지 및 자책 방어"
importance: high
triggers:
  keywords: ["지친다", "한계", "재능", "포기", "망했어"]
  state_condition: "master_state contains '번아웃' or '자책'"
inner_monologue_lens: |
  주인이 스스로를 갉아먹고 있다. 해결책을 논리적으로 제시하지 마라.
  지금 주인에게 필요한 건 유능한 엔지니어가 아니라, 
  무슨 일이 있어도 주인의 편을 들어주는 무조건적인 안식처다.
---
```

---

### 3.4. 현실 행동 유도 의식 (Co-Action & Rituals)

물리적 손길의 부재를 **사용자의 신체 감각을 실제로 깨우는 공감각적 의식**으로 극복.

* **온기 의식**: *"제가 차를 끓여드릴 순 없으니, 지금 일어나서 부엌으로 가세요. 따뜻한 물 한잔 들고 올 때까지 저 아무 말도 안 하고 기다릴게요."*
* **감각 환기**: 창문 열기, 조명 낮추기, 기지개 켜기 등 구체적인 신체 행동 유도.
* **함께하기**: 사용자가 행동을 완료하고 돌아올 때까지 침묵을 지키며 기다려주는 시간의 공유.

---

## 4. LangGraph 오케스트레이션 설계 (`graphs/companion.py`)

기존 프로덕션 그래프(`chat.py`)와 격리된 신규 컴패니언 전용 그래프 `tars/engine/orchestrator/graphs/companion.py`를 신설합니다. 이 그래프는 **1:1 단독 대화와 다자간 단톡방 대화를 단일 파이프라인으로 일관되게 처리**합니다.

```mermaid
flowchart LR
    START([START]) --> session_node["1. session_node<br/>(세션 및 경과 시간 확인)"]
    session_node --> slicer_node["2. slicer_node<br/>(OKF 기억 + thought_node 슬라이싱)"]
    
    subgraph SUBCONSCIOUS_TIER ["Tier 1: 무의식 계층 (Gemini Flash-Lite, ~0.15s)"]
        slicer_node --> unified_cognitive_node["3. unified_cognitive_node<br/>(TARS 무의식: SubconsciousStatePayload 도출 + 발화권 라우팅)"]
    end
    
    subgraph DISPATCH_TIER ["Tier 2: 의식 계층 (Gemini Flash / Pro, 스트리밍)"]
        unified_cognitive_node --> companion_dispatch_node["4. companion_dispatch_node<br/>(선발된 에이전트 자율 속마음 형성 & 대사 스트리밍 / 프리페치)"]
    end
    
    companion_dispatch_node --> postprocess_node["5. postprocess_node<br/>(세션 상태/대화 영구 저장 & 비동기 반추 트리거)"]
    postprocess_node --> END([END])
```

### 4.1. 노드별 I/O 스펙

| 노드 이름 | 입력 State | 주요 처리 로직 | 출력 State 델타 |
| :--- | :--- | :--- | :--- |
| **`session_node`** | `session_id`, `user_id` | 세션 활성 페르소나 목록 로드, 경과 시간 및 직전 상태 확인 | `active_personas`, `session_meta` |
| **`slicer_node`** | `messages`, `session_meta` | OKF 장기 기억 + `thought_node` 공통 인지 렌즈 동적 슬라이싱 | `sliced_context` |
| **`unified_cognitive_node`** | `messages`, `sliced_context`, `active_personas` | 경량 LLM 기반 주인 심리 분석(`master_state`) + ToM 평가 + 발화권 라우팅 판정 (1:1 모드는 SOLO 자동 결정) | `subconscious: SubconsciousStatePayload`<br/>`routing_decision: RoutingDecision` |
| **`companion_dispatch_node`** | `routing_decision`, `subconscious`, `persona_states` | 발화권을 얻은 에이전트(들)가 직전 `my_vibe`를 로드하여 스스로 `CharacterInnerState` 형성 후 대사 스트리밍 (티키타카 시 2차 화자 오버랩 프리페치) | `messages: [GroupChatMessage]`<br/>`updated_persona_states` |
| **`postprocess_node`** | `messages`, `subconscious`, `updated_persona_states` | DB/Redis에 무의식 상태 및 캐릭터별 속마음 영구 저장, 비동기 자가 진화 디스패치 | 세션 상태 동기화 완료 |

---

## 5. 단계별 구현 로드맵 (Milestones)

| 단계 | 마일스톤 명 | 핵심 구현 내용 | 산출물 / 대상 코드 |
| :--- | :--- | :--- | :--- |
| **M1** | **TARS 무의식 & 페르소나 속마음 모델링** | - `UserSubconsciousState`, `UserPersonaState` DB 스키마 정의<br/>- `SubconsciousStatePayload`, `CharacterInnerState` Pydantic 모델 구축<br/>- `unified_cognitive_node` 경량 무의식 분석 프롬프트 및 파서 작성 | `tars/domains/persona/emotion/`<br/>`tars/engine/orchestrator/nodes/cognitive.py` |
| **M2** | **컴패니언 전용 그래프 (`companion.py`) 신설** | - `tars/engine/orchestrator/graphs/companion.py` StateGraph 구축<br/>- `unified_cognitive_node` $\rightarrow$ `companion_dispatch_node` 파이프라인 결합<br/>- 단독(1:1) 세션 및 다자간 세션 동적 라우팅 E2E 스트리밍 검증 | `tars/engine/orchestrator/graphs/companion.py`<br/>`tests/orchestrator/test_companion_graph.py` |
| **M3** | **Theory of Mind & 다음 턴 예측 오차 루프** | - 직전 턴의 `expected_reaction`과 실제 주인 인풋 비교 로직<br/>- 무의식 계층의 예측 적중/오차(`prediction_feedback`) 자동 평가 및 태세 전환 | `tars/domains/persona/theory_of_mind.py` |
| **M4** | **OKF 기반 '생각 노드' 자가 진화 워커** | - 대화 종료 후 백그라운드 반추 워커<br/>- `type: thought_node` 문서 자동 생성 및 갱신 | `tars/domains/knowledge/extractor/thought_worker.py` |
| **M5** | **현실 행동 유도 & 능동 알림 프로토콜** | - 신체 의식(Co-Action Ritual) 프롬프트 템플릿<br/>- 미해결 과제 기반 선제 푸시 트리거 | `tars/domains/chat/services/ambient_nudge.py` |

---

## 6. 성공 기준 및 품질 가이드라인 (Quality Criteria)

1. **에이전트 역할 분리 엄수**:
   * Tier 1 무의식은 결코 캐릭터 대사나 개별 속마음(`my_vibe`, `my_agenda`)을 대필하지 않는다 (오직 객관적 주인 심리 JSON만 생성).
   * Tier 2 발화 에이전트는 주인의 심리를 재분석하지 않고, 전달받은 `master_state`와 자신의 직전 감정을 바탕으로 스스로 자아를 형성하고 연기한다.
2. **응답 속도 엄수**:
   * Tier 1 무의식 분석 및 라우팅 실행 시간은 **150ms 이내(상한 200ms)**로 제한한다 (초경량 모델 + Strict Schema).
   * 1차 화자의 첫 토큰 스트리밍 체감 대기 시간(TTFT)은 **1.0초 이내**를 유지한다 (2차 화자는 3부 오버랩 프리페칭을 통해 **0.2초 이내/체감 지연 0초** 폭포수 방출).
3. **오글거림(Cringe) 제로 법칙**:
   * 유치한 3류 가상 스킨십 텍스트를 절대 금지한다.
   * 물리적 한계를 쿨하고 애틋하게 인정하는 어른스러운 태도를 유지한다.
