import React from 'react';
import { useUIStore } from '@/stores/useUIStore';
import { AuthModal } from './AuthModal';
import { PersonaModal } from './PersonaModal';
import { ToolsModal } from './ToolsModal';
import { SystemStatusModal } from './SystemStatusModal';

export const GlobalModals: React.FC = () => {
  const activeModal = useUIStore((state) => state.activeModal);
  const closeModal = useUIStore((state) => state.closeModal);

  return (
    <>
      <AuthModal isOpen={activeModal === 'auth'} onClose={closeModal} />
      <PersonaModal isOpen={activeModal === 'persona'} onClose={closeModal} />
      <ToolsModal isOpen={activeModal === 'tools'} onClose={closeModal} />
      <SystemStatusModal isOpen={activeModal === 'system'} onClose={closeModal} />
    </>
  );
};
