# TARS 프론트엔드 초기 세팅 및 계층형 아키텍처 가이드

본 문서는 TARS 프로젝트의 프론트엔드 웹 애플리케이션 초기 구축 현황, 기술 스택 선정 배경, 그리고 사람이 보아도 한눈에 파악할 수 있는 **8대 계층형 아키텍처(Layered Architecture)** 설계 규격을 기술합니다.

---

## 1. 개요 및 기술 스택

TARS 프론트엔드는 **유지보수성**, **100% 타입 안정성(End-to-End Type-safety)**, 그리고 **명확한 역할 분리(Separation of Concerns)**를 최우선으로 고려하여 구축되었습니다.

| 구분 | 선택 기술 | 버전 / 규격 | 선정 배경 및 역할 |
| :--- | :--- | :--- | :--- |
| **빌드 & 런타임** | **Vite + React** | React 19 / Vite 8 | 초고속 HMR(핫 리로딩) 및 경량화된 빌드 환경 |
| **언어** | **TypeScript** | 5.x+ | 정적 타입 검증 및 API/라우트 스키마와의 타입 일관성 보장 |
| **페이지 라우팅** | **TanStack Router** | v1 | 100% Type-safe 라우팅, 경로 오타 컴파일 감지, 자동 프리로딩 |
| **서버 비동기 상태** | **TanStack Query** | v5 | 서버 데이터 캐싱, 백그라운드 리페칭, 로딩/에러 라이프사이클 관리 |
| **HTTP 통신 클라이언트** | **Axios** | 1.x | 베이스 URL 설정, 인터셉터(토큰 주입), 공통 네트워크 에러 핸들링 |
| **클라이언트 UI 상태** | **Zustand** | 5.x | 모달/사이드바 토글, 뷰 필터 등 순수 브라우저 UI 상태 관리 (~1KB 경량) |
| **스타일 시스템** | **CSS Modules** | 바닐라 CSS | 외부 UI 프레임워크 의존 없이 컴포넌트 단위 스타일 완벽 격리 |
| **디자인 토큰** | **CSS Variables** | `:root` 규격 | 컬러 팔레트, 타이포그래피, 간격(Spacing), 섀도우 중앙 제어 |
| **노드 버전 관리** | **NVM** | Node.js v24 LTS | 시스템 환경 오염 방지 및 팀 간 일관된 런타임 환경 유지 |

---

## 2. 핵심 설계 개념: 역할의 완벽한 분리

### TanStack Suite & 상태 관리 협업 구조
각 라이브러리는 엄격한 단일 책임(SRP)을 가지며 서로의 영역을 침범하지 않습니다.

```mermaid
flowchart TD
    BrowserURL["Browser URL (/tasks)"] -->|1. Type-safe Route 매칭| TSR["TanStack Router (routes/)"]
    TSR -->|2. 해당 페이지 렌더링| Page["TaskPage (pages/)"]
    Page -->|3. useTasksQuery() 호출| TSQ["TanStack Query (queries/)"]
    Page -->|4. useUIStore() 호출| Zustand["Zustand (stores/)"]
    TSQ -->|5. queryFn: taskApi.getTasks()| Axios["Axios Client (api/)"]
    Axios -->|6. HTTP 통신| Backend[("Backend Server (TARS)")]
```

* **TanStack Router (길잡이)**: URL 경로를 파싱하고 검증하여 적절한 레이아웃과 페이지를 주입합니다. 컴파일 타임에 모든 경로 오타를 감지합니다.
* **Axios (심부름꾼)**: 백엔드 서버와 실제 네트워크 HTTP 패킷을 주고받는 일만 수행합니다. React Hook이나 상태를 전혀 알지 못합니다.
* **TanStack Query (창고 관리자)**: Axios가 가져온 데이터를 메모리에 캐싱하고, 화면에 필요한 `isLoading`, `isError`, `data` 상태를 주입하며, 탭 전환 시 데이터를 최신으로 유지합니다.
* **Zustand (클라이언트 매니저)**: 서버 데이터는 저장하지 않으며, 모달 팝업 상태나 클라이언트 UI 필터 상태만 격리하여 관리합니다.
* **CSS Modules (화가)**: 컴포넌트 단위로 고유 해시 클래스를 부여하여 스타일 충돌을 원천 방지합니다.

---

## 3. 8대 계층 구조 (Layered Architecture)

프로젝트 루트의 `frontend/src/` 디렉토리는 사람이 봐도 한눈에 파일의 역할을 파악할 수 있도록 8개의 계층으로 구조화되어 있습니다.

```text
frontend/src/
├── routes/                 # [Layer 1] 라우팅 계층 (TanStack Router)
│   ├── paths.ts            #  - URL 경로 상수 중앙 관리 (ROUTES.HOME, ROUTES.TASKS)
│   └── router.tsx          #  - RootRoute, 자식 라우트 트리 및 Type-safe Router 정의
│
├── api/                    # [Layer 2] 순수 HTTP 통신 계층 (Axios)
│   ├── client.ts           #  - Axios 전역 인스턴스 (baseURL, 인터셉터 설정)
│   └── endpoints/          #  - 도메인별 순수 API 함수 모음 (queryFn의 실행 주체)
│       └── task.api.ts
│
├── queries/                # [Layer 3] 서버 상태 & 캐시 계층 (TanStack Query)
│   ├── queryClient.ts      #  - QueryClient 인스턴스 (staleTime, retry 기본 옵션)
│   ├── queryKeys.ts        #  - Query Key Factory (캐시 키 오타 방지 팩토리)
│   └── useTaskQuery.ts     #  - useQuery / useMutation 도메인 커스텀 훅
│
├── stores/                 # [Layer 4] 클라이언트 전역 UI 상태 계층 (Zustand)
│   ├── useUIStore.ts       #  - 모달 표시, 사이드바 등 전역 UI 상태
│   └── useFilterStore.ts   #  - 목록 필터링, 정렬 기준 등 뷰 상태
│
├── components/             # [Layer 5] 프레젠테이션 UI 컴포넌트 계층
│   ├── common/             #  - 범용 공통 컴포넌트 (Button, Card 등)
│   │   ├── Button/         #    - Button.tsx + Button.module.css
│   │   └── Card/           #    - Card.tsx + Card.module.css
│   ├── layout/             #  - 레이아웃 뼈대 (Header, Layout + <Outlet />)
│   └── features/           #  - 특정 비즈니스 결합 컴포넌트 (TaskCreateModal)
│
├── pages/                  # [Layer 6] 화면/페이지 조립 계층
│   ├── HomePage/           #  - 메인 대시보드 화면 (/)
│   ├── TaskPage/           #  - 태스크 관리 화면 (/tasks)
│   └── NotFoundPage/       #  - 404 안내 화면 (*)
│
├── styles/                 # [Layer 7] 디자인 토큰 & 글로벌 스타일 시스템
│   ├── reset.css           #  - 모던 CSS 리셋
│   ├── variables.css       #  - CSS 변수 (:root 디자인 토큰)
│   └── global.css          #  - 전역 폰트 및 베이스 스타일
│
├── types/                  # [Layer 8] TypeScript 타입 정의 계층
│   ├── api.types.ts        #  - API 공통 응답 규격 (ApiResponse, ApiError)
│   └── task.types.ts       #  - 도메인 모델 엔티티 타입 (Task, Payload 등)
│
├── App.tsx                 # QueryClientProvider + RouterProvider 최상위 공급자
└── main.tsx                # ReactDOM 진입점
```

---

## 4. 계층 간 작업 규칙 (Do & Don't)

| 계층 | 허용 작업 (DO) | 금지 작업 (DON'T) |
| :--- | :--- | :--- |
| **`routes/`** | - 라우트 트리 구성, 경로 상수 정의<br>- `createRoute`로 페이지 컴포넌트 연결 | - 비즈니스 API 직접 호출<br>- 거대한 UI 마크업 작성 |
| **`api/`** | - `apiClient.get/post` 호출<br>- 요청/응답 직렬화 및 에러 매핑 | - React Hook(`useState`, `useEffect`) 호출<br>- UI 렌더링 코드 작성 |
| **`queries/`** | - `useQuery`, `useMutation` 래핑<br>- 캐시 무효화(`invalidateQueries`) | - 컴포넌트 JSX 반환<br>- 직접 CSS 작성 |
| **`stores/`** | - 모달 토글, 드롭다운 상태 등 UI 상태<br>- 클라이언트 단독 필터/정렬 상태 | - **서버 API 응답 데이터를 여기에 복사/중복 저장** (TanStack Query 캐시와 충돌 유발) |
| **`components/`** | - 재사용 가능한 순수 프레젠테이션 UI<br>- `*.module.css`를 통한 스타일 캡슐화 | - 직접 `apiClient`를 호출하는 행위 (반드시 props나 queries 훅 경유) |
| **`pages/`** | - 하위 계층(queries, stores, components)을 조립한 화면 구성 | - 공통 UI 스타일을 인라인으로 중복 구현 |
| **`styles/`** | - `variables.css`에 의미론적 디자인 토큰 정의 (`--color-primary`) | - 특정 컴포넌트 종속 클래스 선언 |

---

## 5. TanStack Router 활용 가이드

### 경로 이동 및 링크 (Type-safe Link)
하드코딩된 문자열 대신 `ROUTES` 상수를 사용하며, 컴파일러가 유효한 경로인지 검증합니다.
```tsx
import { Link } from '@tanstack/react-router';
import { ROUTES } from '@/routes/paths';

// 1. 일반 링크
<Link to={ROUTES.TASKS}>태스크 관리로 이동</Link>

// 2. 현재 활성화된 링크 스타일 적용
<Link
  to={ROUTES.HOME}
  activeProps={{ className: styles.navLinkActive }}
>
  홈
</Link>
```

### Devtools 내장
* 화면 좌측 하단에 **TanStack Router Devtools**가 활성화되어 있어 현재 활성 라우트, 파라미터, 라우트 트리를 시각적으로 탐색할 수 있습니다.
* 화면 우측 하단에는 **TanStack Query Devtools**가 장착되어 있어 캐시 및 쿼리 상태를 동시에 모니터링할 수 있습니다.

---

## 6. 스타일링 및 CSS 모듈화 규칙

외부 CSS-in-JS 라이브러리의 런타임 오버헤드 없이, 표준 **CSS Modules**를 채택했습니다.

1. **파일 명명 규칙**: 컴포넌트와 동일한 디렉토리에 `[ComponentName].module.css` 형태로 생성합니다.
2. **스타일 격리**: 빌드 시 `styles.button` 클래스는 브라우저에 고유 해시로 렌더링되어 전역 오염이 원천 차단됩니다.
3. **디자인 토큰 활용**: 하드코딩된 색상값(`color: #3b82f6;`) 대신 반드시 `var(--color-primary)` 형태로 [`src/styles/variables.css`](file:///home/ryuji/Workspace/TARS/frontend/src/styles/variables.css)의 토큰을 사용합니다.

---

## 7. 개발 및 빌드 환경 가이드

### 환경 세팅 (NVM 기반)
```bash
# NVM 환경 변수 로드
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# frontend 디렉토리 이동
cd frontend
```

### 개발 서버 실행
```bash
npm run dev
# Vite 로컬 서버 시작: http://localhost:5173
```

### 프로덕션 빌드 및 타입 검증
```bash
npm run build
# tsc -b (타입 체크) && vite build (번들링)
```

---

## 8. 백엔드(FastAPI TARS)와의 연동 안내

1. **환경 변수 설정**:
   `frontend/.env` 파일을 생성하고 백엔드 엔드포인트를 지정합니다.
   ```env
   VITE_API_BASE_URL=http://localhost:8000/api
   ```
2. **Mock Fallback 내장**:
   현재 [`frontend/src/api/endpoints/task.api.ts`](file:///home/ryuji/Workspace/TARS/frontend/src/api/endpoints/task.api.ts)에는 백엔드 서버가 아직 실행되지 않은 상태에서도 프론트엔드 UI/기능(조회, 추가, 토글, 삭제)을 독립적으로 검증할 수 있는 LocalStorage 기반 Mock Fallback이 구현되어 있습니다. 백엔드 API가 준비되면 자동으로 실제 API 엔드포인트와 연동됩니다.
