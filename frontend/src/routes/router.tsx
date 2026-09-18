import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router';
import { TanStackRouterDevtools } from '@tanstack/router-devtools';
import { Layout } from '@/components/layout/Layout';
import { ChatPage } from '@/pages/ChatPage/ChatPage';
import { OAuthCallbackPage } from '@/pages/OAuthCallbackPage/OAuthCallbackPage';
import { NotFoundPage } from '@/pages/NotFoundPage/NotFoundPage';
import { GlobalModals } from '@/components/modals/GlobalModals';

/**
 * 1. Root Route 정의
 */
const rootRoute = createRootRoute({
  component: () => (
    <>
      <Layout />
      <GlobalModals />
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
  component: ChatPage,
});

const oauthCallbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/oauth/callback',
  component: OAuthCallbackPage,
});

/**
 * 3. Route Tree 구성
 */
const routeTree = rootRoute.addChildren([indexRoute, oauthCallbackRoute]);

/**
 * 4. Router 인스턴스 생성
 */
export const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultNotFoundComponent: NotFoundPage,
});

/**
 * 5. Type-safety 등록
 */
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
