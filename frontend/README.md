# TARS Frontend Application

Vite + React + TypeScript 기반의 현대적 프론트엔드 프로젝트입니다.  
사람이 코드를 보았을 때 직관적으로 역할과 책임을 파악할 수 있도록 **8대 계층형 아키텍처(Layered Architecture)**로 설계되었습니다.

---

## 🏛 8대 계층형 아키텍처 (Layered Architecture)

```
frontend/src/
├── routes/                 # 1. 라우팅 계층 (TanStack Router)
│   ├── paths.ts            #    URL 경로 상수 (ROUTES.HOME, ROUTES.TASKS)
│   └── router.tsx          #    Type-safe 라우터 트리 정의
│
├── api/                    # 2. HTTP 통신 계층 (Axios)
│   ├── client.ts           #    Axios 인스턴스 (baseURL, 인터셉터)
│   └── endpoints/          #    도메인별 순수 API 호출 함수들 (queryFn 실행 주체)
│
├── queries/                # 3. 서버 상태 계층 (TanStack Query v5)
│   ├── queryClient.ts      #    QueryClient 인스턴스 & 캐시 정책
│   ├── queryKeys.ts        #    Query Key Factory
│   └── useTaskQuery.ts     #    도메인별 useQuery / useMutation 훅
│
├── stores/                 # 4. 클라이언트 전역 상태 계층 (Zustand)
│   ├── useUIStore.ts       #    모달, 사이드바 등 순수 UI 상태
│   └── useFilterStore.ts   #    뷰 필터, 탭 상태 등 클라이언트 전역 상태
│
├── components/             # 5. UI 컴포넌트 계층 (CSS Modules)
│   ├── common/             #    범용 재사용 컴포넌트 (Button, Card 등)
│   ├── layout/             #    화면 골격 컴포넌트 (Header, Layout + <Outlet />)
│   └── features/           #    비즈니스 단위 복합 컴포넌트 (TaskCreateModal)
│
├── pages/                  # 6. 화면/페이지 조립 계층
│   ├── HomePage/           #    메인 대시보드 화면 (/)
│   ├── TaskPage/           #    태스크 관리 화면 (/tasks)
│   └── NotFoundPage/       #    404 에러 화면 (*)
│
├── styles/                 # 7. 스타일 시스템 (순수 바닐라 CSS)
│   ├── reset.css           #    모던 CSS 리셋
│   ├── variables.css       #    CSS Custom Properties 디자인 토큰
│   └── global.css          #    전역 바디 스타일 및 토큰 import
│
├── types/                  # 8. 타입 정의 계층
│   ├── api.types.ts        #    API 공통 응답 규격
│   └── task.types.ts       #    도메인 모델 엔티티 타입
│
├── App.tsx                 # QueryClientProvider + RouterProvider 최상위 진입점
└── main.tsx                # React DOM 렌더링 엔트리
```

---

## 🚀 빠른 시작

```bash
# 1. frontend 디렉토리 이동
cd frontend

# 2. 개발 서버 시작
npm run dev

# 3. 타입 체크 및 프로덕션 빌드
npm run build
```

자세한 아키텍처 규격 및 가이드는 프로젝트 루트의 [`docs/frontend_architecture_setup_guide.md`](../docs/frontend_architecture_setup_guide.md) 문서를 참고하세요.
