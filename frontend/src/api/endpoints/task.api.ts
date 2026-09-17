import { apiClient } from '../client';
import type { Task, CreateTaskPayload } from '@/types/task.types';

// 백엔드 미연결 시 로컬스토리지 Mock 데이터 폴백
const STORAGE_KEY = 'mock_tasks_data';

const getInitialMockTasks = (): Task[] => {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch {
      // parse fail
    }
  }
  const defaults: Task[] = [
    {
      id: '1',
      title: '계층형 아키텍처 구조 잡기',
      description: 'api -> queries -> stores -> components 계층 분리',
      isCompleted: true,
      createdAt: new Date().toISOString(),
    },
    {
      id: '2',
      title: 'TanStack Query 연동 테스트',
      description: 'Axios와 useQuery를 활용한 데이터 페칭 검증',
      isCompleted: false,
      createdAt: new Date().toISOString(),
    },
    {
      id: '3',
      title: 'Zustand 전역 모달 상태 테스트',
      description: '클라이언트 UI 상태 격리 관리 확인',
      isCompleted: false,
      createdAt: new Date().toISOString(),
    },
  ];
  localStorage.setItem(STORAGE_KEY, JSON.stringify(defaults));
  return defaults;
};

/**
 * Task API 엔드포인트 함수들
 * - 순수한 네트워크 요청 로직만 담당합니다.
 * - 실제 백엔드가 가동 중이면 apiClient를 호출하고, 실패 시 로컬 Mock으로 부드럽게 대체됩니다.
 */
export const taskApi = {
  // 전체 목록 조회
  async getTasks(): Promise<Task[]> {
    try {
      const response = await apiClient.get<Task[]>('/tasks');
      return response.data;
    } catch {
      // Mock 지연 시뮬레이션
      await new Promise((r) => setTimeout(r, 400));
      return getInitialMockTasks();
    }
  },

  // 새 태스크 생성
  async createTask(payload: CreateTaskPayload): Promise<Task> {
    try {
      const response = await apiClient.post<Task>('/tasks', payload);
      return response.data;
    } catch {
      await new Promise((r) => setTimeout(r, 300));
      const tasks = getInitialMockTasks();
      const newTask: Task = {
        id: Date.now().toString(),
        title: payload.title,
        description: payload.description,
        isCompleted: false,
        createdAt: new Date().toISOString(),
      };
      const updated = [newTask, ...tasks];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      return newTask;
    }
  },

  // 태스크 상태 토글
  async toggleTask(id: string): Promise<Task> {
    try {
      const response = await apiClient.patch<Task>(`/tasks/${id}/toggle`);
      return response.data;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
      const tasks = getInitialMockTasks();
      const target = tasks.find((t) => t.id === id);
      if (!target) throw new Error('Task not found');
      target.isCompleted = !target.isCompleted;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
      return target;
    }
  },

  // 태스크 삭제
  async deleteTask(id: string): Promise<void> {
    try {
      await apiClient.delete(`/tasks/${id}`);
    } catch {
      await new Promise((r) => setTimeout(r, 200));
      const tasks = getInitialMockTasks().filter((t) => t.id !== id);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
    }
  },
};
