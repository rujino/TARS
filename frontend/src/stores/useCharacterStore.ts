import { create } from 'zustand';

export type CharacterActionState = 'idle' | 'thinking' | 'tool_use' | 'speaking' | 'interrupted';

interface CharacterStoreState {
  veraState: CharacterActionState;
  miuState: CharacterActionState;
  activeSpeaker: 'vera' | 'miu' | null;

  // Actions
  setVeraState: (state: CharacterActionState) => void;
  setMiuState: (state: CharacterActionState) => void;
  setCharacterState: (speaker: 'vera' | 'miu', state: CharacterActionState) => void;
  setActiveSpeaker: (speaker: 'vera' | 'miu' | null) => void;
  resetAllToIdle: () => void;
}

export const useCharacterStore = create<CharacterStoreState>((set) => ({
  veraState: 'idle',
  miuState: 'idle',
  activeSpeaker: null,

  setVeraState: (state) => set({ veraState: state }),
  setMiuState: (state) => set({ miuState: state }),
  setCharacterState: (speaker, state) =>
    set((prev) => (speaker === 'vera' ? { veraState: state } : { miuState: state })),
  setActiveSpeaker: (speaker) => set({ activeSpeaker: speaker }),
  resetAllToIdle: () =>
    set({
      veraState: 'idle',
      miuState: 'idle',
      activeSpeaker: null,
    }),
}));

if (typeof window !== 'undefined') {
  (window as unknown as { __tarsCharacterStore: typeof useCharacterStore }).__tarsCharacterStore = useCharacterStore;
}
