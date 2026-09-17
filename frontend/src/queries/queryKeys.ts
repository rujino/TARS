/**
 * Query Key Factory
 * - 문자열 하드코딩 오타를 방지하고 일관된 캐시 무효화를 보장합니다.
 */
export const queryKeys = {
  tasks: {
    all: ['tasks'] as const,
    lists: () => [...queryKeys.tasks.all, 'list'] as const,
    list: (filter?: string) => [...queryKeys.tasks.lists(), { filter }] as const,
    details: () => [...queryKeys.tasks.all, 'detail'] as const,
    detail: (id: string) => [...queryKeys.tasks.details(), id] as const,
  },
};
