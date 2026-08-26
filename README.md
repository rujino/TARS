# TARS 🤖

> *"Humor: 90%, Honesty: 95%"*

영화 *인터스텔라*의 AI 로봇 TARS를 오마주한 **오브젝트 스토리지 + DB + OKF 삼위일체 기반 벤더 무관 하이브리드 AI 동반자 서빙 시스템**입니다.

## 📌 주요 문서
- [OKF 지식 명세서 (OKF_SPEC.md)](file:///Users/jinhoryu/Workspace/SideProject/TARS/docs/OKF_SPEC.md)
- [기술 스택 정의서 (TECH_STACK.md)](file:///Users/jinhoryu/Workspace/SideProject/TARS/docs/TECH_STACK.md)
- [시스템 아키텍처 정의서 (ARCHITECTURE.md)](file:///Users/jinhoryu/Workspace/SideProject/TARS/docs/ARCHITECTURE.md)
- [프로젝트 요구사항 정의서 (PRD.md)](file:///Users/jinhoryu/Workspace/SideProject/TARS/docs/PRD.md)
- [아이디어 & 컨셉 노트 (IDEAS.md)](file:///Users/jinhoryu/Workspace/SideProject/TARS/docs/IDEAS.md)

## 🏗️ 시스템 아키텍처 요약
- **Storage & Knowledge Trinity**: **Object/File Storage** (지식 원본 `.md`) + **RDBMS** (메타데이터/인증) + **OKF 표준** (지식 규격)
- **Knowledge Evolution & Slicing**: **5-Factor 점수화 기반 동적 슬라이서** + **대화 기반 비동기 OKF 파일 자동 생성 & 자가 학습 루프**
- **Smart Session & Proactive Greeting**: **시간 감쇄(15분/2시간) 및 주제 전환 감지 스마트 세션 라우팅** + **앱 진입 시 선제 화제 제시(능동 오프닝 API)**
- **Acceleration**: **정적 툴 스키마 CAG** (75% 비용 절감 & 저지연)
- **Agent Orchestration**: **LangGraph (A2A 커스텀 상태 머신 & ReAct 도구 루프)**
- **Tool Ecosystem & Plugin Hub**: **MCP (JSON-RPC 2.0 / HTTP, SSE, STDIO, Mock)** + **Google Workspace(Calendar, Gmail)** + **사용자별 원클릭 토글형 플러그인 허브**
- **Hybrid LLM Engine**: **Google Gemini API** (사용자 대화 응답 100% 전담) + **`llama.cpp`** (로컬 GPU 기반 내부 경량 추론 & 전처리 전담)
- **Observability**: **Langfuse** (실시간 트레이싱 및 디버깅)
- **Backend Server**: FastAPI + Nginx + Let's Encrypt SSL (JWT 인증, SSE & WebSocket 토큰 스트리밍)
- **Edge Client (iPhone)**: PWA Web / iOS App + **On-Device TTS (음성 합성)**
- **Development (Mac)**: Python (`uv`) 가상환경 기반 백엔드 및 앱 개발
- **Protocol**: Standard HTTPS/WSS (Let's Encrypt + Domain)