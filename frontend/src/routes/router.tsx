import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router';
import { TanStackRouterDevtools } from '@tanstack/router-devtools';
import { Layout } from '@/components/layout/Layout';
import { HomePage } from '@/pages/HomePage/HomePage';
import { TaskPage } from '@/pages/TaskPage/TaskPage';
import { NotFoundPage } from '@/pages/NotFoundPage/NotFoundPage';
import { TaskCreateModal } from '@/components/features/TaskCreateModal/TaskCreateModal';

/**
 * 1. Root Route 정의
 * - 모든 페이지의 공통 셸 (Layout, 전역 모달, Router Devtools)
 */
const rootRoute = createRootRoute({
  component: () => (
    <>
      <Layout />
      <TaskCreateModal />
      {/* TanStack Router Devtools (우측 하단) */}
      <TanStackRouterDevtools position="bottom-left" initialIsOpen={false} />
    </>
  ),
  notFoundComponent: NotFoundPage,
});

/**
 * 2. 페이지 라우트 정의
 */
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

const tasksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tasks',
  component: TaskPage,
});

/**
 * 3. Route Tree 구성
 */
const routeTree = rootRoute.addChildren([indexRoute, tasksRoute]);

/**
 * 4. Router 인스턴스 생성
 */
export const router = createRouter({
  routeTree,
  defaultPreload: 'intent', // 호버 시 라우트 데이터 프리로딩
  defaultNotFoundComponent: NotFoundPage,
});

/**
 * 5. Type-safety 등록
 * - Link 컴포넌트나 useNavigate에서 완전한 자동완성 및 타입 검증을 제공합니다.
 */
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
