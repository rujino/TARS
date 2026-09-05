# TARS OKF (Open Knowledge Format 1.0) 명세서 (OKF_SPEC.md)

TARS의 지식 베이스(`llmwiki`)는 **OKF (Open Knowledge Format 1.0)** 표준 규격을 따라 구조화된 마크다운 문서로 영속화되며, **"대화 중 실시간 자가 학습 및 지식 진화(Self-Evolving Knowledge Loop)"**와 **"5-Factor 동적 지식 슬라이싱"**을 지원합니다.

---

## 1. OKF 문서 기본 구조 (Schema Structure)

모든 OKF 문서는 **YAML Frontmatter (구조화된 메타데이터)**와 **Markdown 본문 (지식 상세 내용)**의 2계층 구조로 구성됩니다.

```markdown
---
okf_version: "1.0"
id: "user_pref_001"
type: "preference"        # [concept | rule | entity | procedure | preference]
title: "TARS 유머 지수 및 커뮤니케이션 규칙"
category: "persona_settings"
tags: ["interstellar", "humor", "custom_rule"]
importance: "high"       # [low | medium | high | critical]
source: "auto_extracted"  # [manual | auto_extracted | system]
relations:
  depends_on: []
  related_to: ["core_tars_persona", "honesty_setting"]
created_at: "2026-08-18"
updated_at: "2026-08-18"
---

# TARS 유머 지수 및 커뮤니케이션 규칙

사용자는 인터스텔라의 무덤덤한 유머 스타일을 선호함.
- 대화 시 툭 던지는 드라이한 유머(90%) 유지
- 과도한 이모지나 경박한 톤 배제
- 지시사항에 대해 충성스럽지만 촌철살인의 위트 포함
```

---

## 2. OKF 핵심 메타데이터 필드 정의

| 필드명 | 타입 | 필수 여부 | 설명 |
| :--- | :--- | :---: | :--- |
| `okf_version` | String | **필수** | OKF 스펙 버전 (`"1.0"`) |
| `id` | String | **필수** | 유저 스코프 내 고유 식별자 (Slug / UUID) |
| `type` | Enum | **필수** | 지식 유형 (`concept`, `rule`, `entity`, `procedure`, `preference`) |
| `title` | String | **필수** | 문서 제목 (간결한 요약 문구) |
| `category` | String | 선택 | 지식 대분류 카테고리 (`schedule`, `project`, `persona_settings` 등) |
| `tags` | Array[String] | 선택 | 고속 검색 및 필터링용 키워드 태그 목록 |
| `importance` | Enum | 선택 | 우선순위 가중치 (`low`, `medium`, `high`, `critical`) |
| `source` | Enum | **필수** | 생성 출처 (`manual`: 사용자 직접 작성, `auto_extracted`: 대화 중 TARS가 자동 추출, `system`: 시스템 기본값) |
| `relations` | Object | 선택 | 타 OKF 문서와의 관계망 (`depends_on`, `related_to`) |
| `created_at` | Date/String | 선택 | 최초 생성일 (ISO-8601 포맷) |
| `updated_at` | Date/String | 선택 | 최근 수정일 (ISO-8601 포맷) |

---

## 3. 5-Factor 동적 지식 슬라이서 (`DynamicSlicerEngine`)

TARS는 사용자의 질문이 들어왔을 때 저장소 내 모든 OKF 문서를 무차별 주입하지 않고, 5가지 요소를 종합 점수화하여 질문과 가장 밀접한 문서를 최대 **1,500 토큰 예산** 내로 동적 패킹합니다.

### 3.1. 5-Factor 점수 산출 공식
$$\text{Total Score} = W_c \cdot S_{\text{context}} + W_i \cdot S_{\text{importance}} + W_t \cdot S_{\text{type}} + W_r \cdot S_{\text{relations}} + W_d \cdot S_{\text{recency}}$$

1. **Context Relevance ($S_{\text{context}}$)**: 사용자 쿼리와 문서 제목/태그/본문 간의 키워드 및 의미론적 일치도.
2. **Importance Weight ($S_{\text{importance}}$)**: `critical` (1.0), `high` (0.8), `medium` (0.5), `low` (0.2).
3. **Type Priority ($S_{\text{type}}$)**: 행동 지침을 규정하는 `rule`/`preference`에 높은 가중치 부여.
4. **Relations Network ($S_{\text{relations}}$)**: 상위 선택된 문서가 `depends_on` 또는 `related_to`로 참조하는 연관 문서에 가산점 부여.
5. **Recency Decay ($S_{\text{recency}}$)**: 최근 생성 또는 수정된 문서일수록 높은 점수 유지.

---

## 4. 대화 기반 자가 학습 파이프라인 (Self-Evolving Knowledge Loop)

TARS는 대화 턴이 종료되면 비동기 백그라운드 워커(`SelfEvolvingKnowledgeWorker`)를 통해 사용자의 선호도, 새로운 규칙, 일정, 중요한 사실을 자동으로 감지하여 OKF 문서로 저장합니다.

```text
 1. [사용자 대화 완료]
    사용자: "앞으로 나는 아침 8시 이전 회의는 절대 잡지 않는 규칙을 정할게."
    TARS 답변: "알겠습니다 파트너. 오전 8시 이전 회의는 전자기 펄스로 즉각 무력화하겠습니다."

 2. [비동기 지식 추출 워커 디스패치]
    - 대화 텍스트에서 지식 가치 평가 및 사실/선호도 추출 (Gemini 심층)
    - 새로운 정보 감지 ➔ OKF 포맷으로 자동 변환

 3. [자동 생성된 OKF 파일]
    경로: storage/users/{user_id}/wikis/rule_no_early_morning_meeting.md
    ---
    okf_version: "1.0"
    id: "rule_no_early_morning_meeting"
    type: "rule"
    title: "오전 8시 이전 회의 금지 규칙"
    category: "schedule"
    tags: ["meeting", "morning", "work_rule"]
    importance: "high"
    source: "auto_extracted"
    ---
    # 오전 8시 이전 회의 금지 규칙
    - 오전 08:00 이전에는 어떤 회의도 잡지 않음.

 4. [DB 메타데이터 동기화 & 프롬프트 즉각 반영]
    - PostgreSQL `user_wikis` 테이블에 원자적 Upsert (file_path, updated_at).
    - 다음 대화 턴부터 5-Factor 슬라이서에 즉시 검색되어 TARS가 기억하고 행동!
```

---

## 5. 지식 충돌 해결 및 버전 관리 (Conflict Resolution)

- 기존 지식과 상반된 대화가 발생할 경우 (예: *"회의 금지 시간 9시로 바꿨어"*), 추출 워커가 기존 OKF 문서를 매칭하여 본문 및 태그를 최신 정보로 갱신하고 `updated_at` 타임스탬프를 갱신합니다.
- 물리적 파일시스템 기반이므로 언제든 옵시디언(Obsidian) 또는 Git을 통해 사용자가 직접 수정하거나 형상 관리할 수 있습니다.

