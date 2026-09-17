/**
 * 애플리케이션 라우트 경로 상수
 * - 하드코딩된 문자열 URL 대신 상수를 사용하여 경로 변경 및 오타를 방지합니다.
 */
export const ROUTES = {
  HOME: '/',
  TASKS: '/tasks',
} as const;

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES];
