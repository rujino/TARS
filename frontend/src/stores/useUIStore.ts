import { create } from 'zustand';

interface UIState {
  isCreateModalOpen: boolean;
  openCreateModal: () => void;
  closeCreateModal: () => void;
}

/**
 * 전역 UI 클라이언트 상태 스토어
 * - 서버 데이터와 무관한 순수 뷰/인터랙션 상태만 관리합니다.
 */
export const useUIStore = create<UIState>((set) => ({
  isCreateModalOpen: false,
  openCreateModal: () => set({ isCreateModalOpen: true }),
  closeCreateModal: () => set({ isCreateModalOpen: false }),
}));
