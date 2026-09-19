/**
 * 애플리케이션 라우트 경로 상수
 */
export const ROUTES = {
  HOME: '/',
  OAUTH_CALLBACK: '/oauth/callback',
} as const;

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES];
