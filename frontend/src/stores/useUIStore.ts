import { create } from 'zustand';

export type ModalType = 'auth' | 'persona' | 'tools' | 'system' | null;

interface UIState {
  activeModal: ModalType;
  openModal: (modal: Exclude<ModalType, null>) => void;
  closeModal: () => void;

  // TTS (gemini-tts 확장 대비) On/Off 상태
  isTtsEnabled: boolean;
  toggleTts: () => void;
  setTtsEnabled: (enabled: boolean) => void;
}

export const useUIStore = create<UIState>((set) => ({
  activeModal: null,
  openModal: (modal) => set({ activeModal: modal }),
  closeModal: () => set({ activeModal: null }),

  isTtsEnabled: typeof window !== 'undefined' ? localStorage.getItem('tars_tts_enabled') === 'true' : false,
  toggleTts: () =>
    set((state) => {
      const next = !state.isTtsEnabled;
      if (typeof window !== 'undefined') {
        localStorage.setItem('tars_tts_enabled', String(next));
      }
      return { isTtsEnabled: next };
    }),
  setTtsEnabled: (enabled) => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('tars_tts_enabled', String(enabled));
    }
    set({ isTtsEnabled: enabled });
  },
}));
