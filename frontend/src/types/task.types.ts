/**
 * Task 도메인 모델 타입
 */
export interface Task {
  id: string;
  title: string;
  description?: string;
  isCompleted: boolean;
  createdAt: string;
}

export interface CreateTaskPayload {
  title: string;
  description?: string;
}

export interface UpdateTaskPayload {
  title?: string;
  description?: string;
  isCompleted?: boolean;
}
