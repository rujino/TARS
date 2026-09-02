# TARS 시스템 아키텍처 정의서 (ARCHITECTURE.md)

## 1. 시스템 개요 (System Overview)
TARS 프로젝트는 **"오브젝트 스토리지(지식 원본) + RDBMS(메타데이터) + OKF(표준 지식 규격)"**의 삼위일체(Trinity) 구조를 기반으로 하는 프로덕션급 멀티 테넌트 AI 에이전트 플랫폼입니다.

동적으로 변화하는 사용자 지식(`llmwiki`)은 파일 스토리지의 순수 **OKF 마크다운 문서**로 보관하여 벤더 종속성을 원천 차단하고, DB는 **초경량 메타데이터(Path, User, Auth)**만을 관리하여 극상의 성능과 데이터 무결성을 보장합니다.

---

### 2. K3s 기반 분리형 스토리지 & 하이브리드 추론 아키텍처 다이어그램

```text
 [ 📱 아이폰 클라이언트 (Edge Device) ]
     │
     │ (HTTPS / WSS 보안 통신, JWT 인증)
     ▼
 ┌─────────────────────────── [ ☸️ K3s Production Edge Cluster ] ───────────────────────────┐
 │                                                                                         │
 │   [ 🌐 Ingress & Security Layer (Traefik + cert-manager) ]                              │
 │     └─ Let's Encrypt 자동 SSL/TLS 종단, HTTP->HTTPS 리다이렉트, SSE/WebSocket 무지연 프록시  │
 │                                                                                         │
 │   ┌─────────────────────── [ 🚀 tars-backend (3 Replicas) ] ────────────────────────┐   │
 │   │                                                                                 │   │
 │   │   [ 1. OKF Engine & Dynamic Slicing ]                                           │   │
 │   │     ├─ 문서 헤더(YAML Frontmatter) 초고속 파싱 ➔ 지식 지도(Knowledge Map) 구성   │   │
 │   │     └─ 5-Factor 점수화로 대화 맥락과 관련된 OKF 문서 원문을 프롬프트에 동적 주입 │   │
 │   │                                                                                 │   │
 │   │   [ 2. LangGraph Orchestration (A2A StateGraph) ]                               │   │
 │   │     ├─ SLM Node (llama-server) : 내부 경량 추론 (의도 분류, 쿼리 전처리, 키워드 추출)  │   │
 │   │     ├─ Tool Node               : MCP / Google Workspace 도구 실행               │   │
 │   │     └─ Gemini Node             : [정적 CAG 툴 스키마] + [동적 OKF 문서 원문]     │   │
 │   │           ├─ 사용자 대화 응답(User-Facing Response) 100% 전담 (TARS 페르소나 발화) │   │
 │   │           └─ 심층 내부 추론 (다단계 계획, 지식 충돌 해결, 툴 인자 파싱 및 결과 합성)  │   │
 │   │                                                                                 │   │
 │   │   [ 3. Background Extractor (비동기 지식 자가 진화) ]                           │   │
 │   │     └─ 대화 속 중요 정보 감지(Gemini 심층) ➔ 새 OKF 파일 생성 ➔ 스토리지/DB 저장 │   │
 │   │                                                                                 │   │
 │   │   [ 4. Observability: Langfuse ] (대화 및 툴 호출 전과정 트레이싱 & 모니터링)     │   │
 │   └─────────────────────────────────────────────────────────────────────────────────┘   │
 │                                    │                    │                               │
 │           (tars-storage-pvc / tars-data-pvc)     (tars-db:5432 asyncpg)                 │
 │                                    ▼                    ▼                               │
 │   [ 📁 Storage Layer (PVC 10Gi) ]     [ 🗄️ Database Layer (tars-db 10Gi PVC) ]            │
 │   사용자별 OKF 마크다운 원본 문서     PostgreSQL 16: 회원/설정/세션/메타데이터           │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
 [ 🦙 로컬 SLM (llama-server) ]                [ ☁️ Google Cloud (Gemini API) ]
 (GGUF 경량 C++ 추론: 의도분류/전처리)          (고지능 페르소나 대화 생성 100% 전담)
```

---

## 3. 핵심 시스템 엔지니어링 포인트 (Core Engineering Principles)

1. **오브젝트 스토리지 + RDBMS 분리형 멀티테넌트 아키텍처 (Enterprise Storage Pattern)**:
   - 지식 원본은 파일 스토리지(`.md`)에, 메타데이터는 DB에 분리 저장하여 **Zero Data Loss(데이터 무결성)**와 **초고속 쿼리 성능**을 동시에 달성.
2. **OKF (Open Knowledge Format) 표준 엔진**:
   - YAML Frontmatter + Markdown 구조를 직접 파싱/탐색하는 전용 엔진을 구축하여 완벽한 Vendor-Agnostic 지식 주입 실현.
3. **하이브리드 추론 분리 & 어댑터 패턴 (Hybrid Inference & Engine Isolation)**:
   - **역할 분리**: 사용자 페르소나 발화 및 복잡한 추론은 Cloud Gemini가 전담하고, 빠른 의도 분류/전처리는 로컬 `llama.cpp`가 전담하여 API 비용과 응답 지연을 동시 최적화.
   - **엔진 경량화 & 확장성**: 단일 머신 자원 제약 하에서 VRAM 선점(Pre-allocation)이 없는 C++/GGUF 런타임을 채택하였으며, OpenAI 호환 규격 어댑터 인터페이스로 구현되어 향후 대규모 배치 서빙 엔진(vLLM 등)으로의 전환 호환성 확보.
4. **정적 CAG(툴 스키마 캐싱) + 동적 OKF 슬라이싱 분리**:
   - 고정된 도구 스키마만 캐싱하여 75% 비용 절감 및 지연 시간 최소화.
5. **Self-Evolving Knowledge Loop**:
   - 비동기 백그라운드 지식 추출을 통한 지속적인 OKF 파일 자동 생성 및 자가 학습.
6. **음성 우선 능동 대화 & 스마트 세션 라이프사이클 (Voice-First Session Architecture)**:
   - **App-Launch Greeting**: 앱 실행 즉시 시간대/이전 맥락/OKF 지식을 결합해 1~2문장의 능동 오프닝을 먼저 발화하고 마이크 리스닝 모드로 즉시 전환.
   - **Dual-Layer Memory**: 단기 작업 기억(Session/Context Window)은 시간 경과/주제 전환에 따라 기민하게 분기/초기화하고, 장기 기억은 비동기 OKF 파일로 영구 보존하여 세션 단절 없는 연속성 보장.
7. **사용자별 토글형 원클릭 플러그인 허브 (User-Scoped Toggleable Tool Hub)**:
   - 사용자마다 원하는 도구(Google Workspace, 개인 Notion, 공용 날씨/뉴스 MCP, 로컬 파일시스템 MCP 등)를 UI에서 스위치 토글로 활성화.
   - 내부의 복잡한 전송 방식(`stdio` 프로세스 파이프, 원격 `SSE/HTTP` 네트워크, OAuth2 토큰 갱신)을 사용자 모르게 완전히 은닉화(캡슐화).
   - 대화 세션 시 해당 유저의 권한과 활성화 목록에 맞춘 `ToolRegistry`를 동적으로 조립 및 주입(Per-User Tool Assembly).
8. **K3s 기반 단일 노드 엣지 오케스트레이션 (Lightweight Production Orchestration)**:
   - 온프레미스/홈서버 환경에서 표준 k8s의 선언적 인프라(Deployment, Service DNS, PVC 영구 볼륨, Secret 격리, 자동 재시작) 및 Traefik/cert-manager를 통한 HTTPS/WSS 자동화를 마스터 메모리 1GB 미만의 초경량 오버헤드로 운영.
9. **On-Device TTS & Client Performance**:
   - 온디바이스 TTS로 서버 부하 0% 달성 및 네트워크 트래픽 초경량화.

