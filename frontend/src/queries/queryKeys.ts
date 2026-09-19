/**
 * Query Key Factory
 * - 일관된 캐시 관리와 손쉬운 무효화(invalidateQueries)를 위한 계층형 쿼리 키 정의
 */
export const queryKeys = {
  auth: {
    all: ['auth'] as const,
    me: () => [...queryKeys.auth.all, 'me'] as const,
  },
  chat: {
    all: ['chat'] as const,
    greeting: (tz?: string) => [...queryKeys.chat.all, 'greeting', tz ?? 'Asia/Seoul'] as const,
    sessions: () => [...queryKeys.chat.all, 'sessions'] as const,
    messages: (sessionId: string) => [...queryKeys.chat.all, 'messages', sessionId] as const,
  },
  persona: {
    all: ['persona'] as const,
    config: () => [...queryKeys.persona.all, 'config'] as const,
  },
  tools: {
    all: ['tools'] as const,
    servers: () => [...queryKeys.tools.all, 'servers'] as const,
    googleCredentials: () => [...queryKeys.tools.all, 'googleCredentials'] as const,
  },
  system: {
    all: ['system'] as const,
    health: () => [...queryKeys.system.all, 'health'] as const,
    liveness: () => [...queryKeys.system.all, 'liveness'] as const,
    readiness: () => [...queryKeys.system.all, 'readiness'] as const,
    metrics: () => [...queryKeys.system.all, 'metrics'] as const,
  },
};
