# TARS OKF (Open Knowledge Format) 명세서 (OKF_SPEC.md)

TARS의 `llmwiki`는 **OKF (Open Knowledge Format)** 표준 규격을 따라 구조화된 지식 문서로 관리되며, **"대화 중 실시간 자가 학습 및 지식 진화(Self-Evolving Knowledge Loop)"**를 지원합니다.

---

## 1. OKF 문서 기본 구조 (Schema Structure)

모든 OKF 문서는 **YAML Frontmatter (구조화된 메타데이터)**와 **Markdown 본문 (지식 상세 내용)**의 2계층으로 구성됩니다.

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
| `okf_version` | String | **필수** | OKF 스펙 버전 (예: `"1.0"`) |
| `id` | String | **필수** | 유저 내 고유 식별자 (Slug / UUID) |
| `type` | Enum | **필수** | 지식 유형 (`concept`, `rule`, `entity`, `procedure`, `preference`) |
| `title` | String | **필수** | 문서 제목 |
| `category` | String | 선택 | 지식 대분류 카테고리 |
| `tags` | Array[String] | 선택 | 검색 및 필터링용 키워드 태그 |
| `importance` | Enum | 선택 | 우선순위 (`low`, `medium`, `high`, `critical`) |
| `source` | Enum | **필수** | 생성 출처 (`manual`: 사용자 직접 작성, `auto_extracted`: 대화 중 TARS가 자동 추출, `system`: 기본 규칙) |
| `relations` | Object | 선택 | 타 OKF 문서와의 관계망 (`depends_on`, `related_to`) |

---

## 3. 대화 기반 자가 학습 파이프라인 (Self-Evolving Knowledge Loop)

TARS는 사용자와 일상 대화를 나누면서 **사용자의 선호도, 새로운 규칙, 일정, 중요한 사실**을 대화 중에서 자동으로 포착하여 OKF 지식 베이스를 지속적으로 업데이트합니다.

```text
 1. [대화 진행]
    사용자: "TARS, 나 매주 화요일 3시엔 팀 회의가 있으니까 방해하지 마."
    TARS 답변: "알겠습니다 파트너. 화요일 15시는 안전지대로 등록해 두겠습니다."

 2. [비동기 지식 추출 (Background Knowledge Extractor)]
    - 사용자 대화 응답과 동시에 백그라운드 태스크로 지식 가치 평가
    - 새로운 정보 감지 ➔ OKF 포맷으로 자동 변환

 3. [자동 생성된 OKF 문서]
    ---
    okf_version: "1.0"
    id: "user_schedule_weekly_team_meeting"
    type: "rule"
    title: "화요일 정기 팀 회의 방해금지 규칙"
    category: "schedule"
    tags: ["team_meeting", "tuesday", "do_not_disturb"]
    source: "auto_extracted"
    ---
    # 화요일 정기 팀 회의
    - 매주 화요일 15:00 ~ 16:00
    - 집중 회의 시간이므로 알림 및 방해 최소화

 4. [DB Upsert & 다음 대화 즉시 반영]
    - `user_wikis` 테이블에 자동 등록/수정
    - 다음 대화부터 TARS가 이 지식을 기억하고 자연스럽게 행동!
```

---

## 4. 지식 충돌 및 버전 관리 (Conflict Resolution)
- 기존 지식과 상반된 대화가 발생할 경우 (예: *"나 이제 팀 회의 수요일로 바뀌었어"*), 기존 OKF 문서를 찾아 내용을 최신 정보로 갱신하고 `updated_at` 타임스탬프를 업데이트합니다.
