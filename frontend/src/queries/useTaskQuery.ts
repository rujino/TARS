import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { taskApi } from '@/api/endpoints/task.api';
import { queryKeys } from './queryKeys';
import type { CreateTaskPayload } from '@/types/task.types';

/**
 * Task 목록 조회 쿼리 훅
 */
export function useTasksQuery() {
  return useQuery({
    queryKey: queryKeys.tasks.lists(),
    queryFn: () => taskApi.getTasks(),
  });
}

/**
 * Task 생성 뮤테이션 훅
 */
export function useCreateTaskMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTaskPayload) => taskApi.createTask(payload),
    onSuccess: () => {
      // 목록 캐시 무효화 -> 화면 자동 최신화
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists() });
    },
  });
}

/**
 * Task 완료 토글 뮤테이션 훅
 */
export function useToggleTaskMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => taskApi.toggleTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists() });
    },
  });
}

/**
 * Task 삭제 뮤테이션 훅
 */
export function useDeleteTaskMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => taskApi.deleteTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.lists() });
    },
  });
}
