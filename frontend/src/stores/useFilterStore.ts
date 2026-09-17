import { create } from 'zustand';

export type TaskFilterType = 'all' | 'active' | 'completed';

interface FilterState {
  filter: TaskFilterType;
  setFilter: (filter: TaskFilterType) => void;
}

/**
 * Task 필터 상태 스토어
 */
export const useFilterStore = create<FilterState>((set) => ({
  filter: 'all',
  setFilter: (filter) => set({ filter }),
}));
