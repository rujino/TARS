import { create } from 'zustand';

interface SessionState {
  activeSessionId: string | null;
  activeTitle: string | null;
  isSidebarOpen: boolean;
  setActiveSession: (sessionId: string | null, title?: string | null) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (isOpen: boolean) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  activeSessionId: null,
  activeTitle: null,
  isSidebarOpen: true,
  setActiveSession: (sessionId, title) =>
    set({
      activeSessionId: sessionId,
      activeTitle: title ?? null,
    }),
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  setSidebarOpen: (isOpen) => set({ isSidebarOpen: isOpen }),
}));
