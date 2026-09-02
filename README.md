# TARS 🤖

> *"Humor: 90%, Honesty: 95%"*

영화 *인터스텔라*의 AI 로봇 TARS를 오마주한 **오브젝트 스토리지 + DB + OKF 삼위일체 기반 벤더 무관 하이브리드 AI 동반자 서빙 시스템**입니다.

## 📌 주요 문서
- [프로젝트 요구사항 정의서 (PRD.md)](docs/PRD.md)
- [시스템 아키텍처 정의서 (ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- [기술 스택 정의서 (TECH_STACK.md)](docs/TECH_STACK.md)
- [OKF 지식 명세서 (OKF_SPEC.md)](docs/OKF_SPEC.md)
- [아이디어 & 컨셉 노트 (IDEAS.md)](docs/IDEAS.md)
- [K3s 프로덕션 배포 가이드 (DEPLOYMENT.md)](DEPLOYMENT.md)
- [K3s 매니페스트 설명서 (k8s/readme.md)](k8s/readme.md)

## 🏗️ 시스템 아키텍처 요약
- **Storage & Knowledge Trinity**: **Object/File Storage** (지식 원본 `.md`, K3s PVC 10Gi) + **RDBMS** (PostgreSQL 16, PVC 10Gi, 메타데이터/인증/세션) + **OKF 표준** (지식 규격)
- **Knowledge Evolution & Slicing**: **5-Factor 점수화 기반 동적 슬라이서** + **대화 기반 비동기 OKF 파일 자동 생성 & 자가 학습 루프**
- **Smart Session & Proactive Greeting**: **시간 감쇄(15분/2시간) 및 주제 전환 감지 스마트 세션 라우팅** + **앱 진입 시 선제 화제 제시(능동 오프닝 API)**
- **Acceleration**: **정적 툴 스키마 CAG** (75% 비용 절감 & 저지연)
- **Agent Orchestration**: **LangGraph (A2A 커스텀 상태 머신 & ReAct 도구 루프)**
- **Tool Ecosystem & Plugin Hub**: **MCP (JSON-RPC 2.0 / HTTP, SSE, STDIO, Mock)** + **Google Workspace(Calendar, Gmail)** + **사용자별 원클릭 토글형 플러그인 허브**
- **Hybrid LLM Engine**: **Google Gemini API** (사용자 대화 응답 100% 전담) + **`llama.cpp` (`llama-server`)** (K3s/온프레미스 기반 내부 경량 추론 & 전처리 전담)
- **Observability**: **Langfuse** (실시간 트레이싱 및 디버깅)
- **Container Orchestration & Infra**: **K3s (경량 쿠버네티스)** + **Traefik Ingress** + **cert-manager** (Let's Encrypt 자동 SSL/TLS 발급/갱신) + **FastAPI 3 Replicas** (무중단 롤링 업데이트)
- **Edge Client (iPhone)**: PWA Web / iOS App + **On-Device TTS (음성 합성)**
- **Development (Mac)**: Python (`uv`) 가상환경 기반 백엔드 및 앱 개발
- **Protocol**: Standard HTTPS/WSS (Let's Encrypt + Domain)

## 🚀 K3s 프로덕션 원클릭 배포
```bash
# 1. 템플릿 복사 및 비밀번호/키 설정
cp k8s/01-secret.example.yaml k8s/01-secret.yaml
cp k8s/04-cluster-issuer.example.yaml k8s/04-cluster-issuer.yaml
cp k8s/05-ingress.example.yaml k8s/05-ingress.yaml

# 2. 원클릭 빌드 & K3s 배포 실행
bash k8s/deploy.sh
```