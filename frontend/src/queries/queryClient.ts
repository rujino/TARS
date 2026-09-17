import { QueryClient } from '@tanstack/react-query';

/**
 * 전역 TanStack Query 클라이언트 인스턴스
 * - staleTime: 데이터가 '신선'하다고 판단하는 시간 (1분 동안 불필요한 백그라운드 리페칭 방지)
 * - gcTime: 언마운트 후 메모리에 캐시를 유지하는 시간 (5분)
 * - retry: 실패 시 재시도 횟수
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 1, // 1분
      gcTime: 1000 * 60 * 5,    // 5분
      retry: 1,
      refetchOnWindowFocus: false, // 창 전환 시 자동 리페칭 끄기 (선택 사항)
    },
    mutations: {
      retry: 0,
    },
  },
});
