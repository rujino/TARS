import React from 'react';
import modalStyles from './Modal.module.css';
import styles from './PersonaModal.module.css';
import { usePersonaQuery } from '@/queries/usePersonaQuery';

interface PersonaModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const PersonaModal: React.FC<PersonaModalProps> = ({ isOpen, onClose }) => {
  const {
    config,
    isLoadingConfig,
    updateConfig,
    isUpdatingConfig,
    resetConfig,
    isResettingConfig,
  } = usePersonaQuery();

  if (!isOpen) return null;

  const currentMode = config?.mode || 'attend';

  const handleSelectMode = async (mode: 'attend' | 'task') => {
    try {
      await updateConfig({ mode });
    } catch (err: unknown) {
      alert('설정 변경에 실패했습니다: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleReset = async () => {
    if (confirm('TARS 설정을 기본값(Mode: attend)으로 초기화하시겠습니까?')) {
      try {
        await resetConfig();
      } catch (err: unknown) {
        alert('초기화에 실패했습니다: ' + (err instanceof Error ? err.message : String(err)));
      }
    }
  };

  return (
    <div className={modalStyles.backdrop} onClick={onClose}>
      <div className={modalStyles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={modalStyles.modalHeader}>
          <div className={modalStyles.modalTitle}>
            <span>🎭</span>
            <span>TARS 페르소나 및 운영 모드 설정</span>
          </div>
          <button className={modalStyles.closeButton} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div className={modalStyles.modalBody}>
          <div>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-main)' }}>
              운영 모드 선택 (GET/PATCH /api/v1/tars/config)
            </span>
            <p style={{ fontSize: '12px', color: 'var(--color-text-subtle)', marginTop: 2 }}>
              대화 상황과 목적에 맞춰 상호작용 스타일을 즉시 전환합니다.
            </p>
          </div>

          <div className={styles.modeGrid}>
            <button
              className={`${styles.modeCard} ${
                currentMode === 'attend' ? styles.modeCardActive : ''
              }`}
              onClick={() => handleSelectMode('attend')}
              disabled={isUpdatingConfig || isLoadingConfig}
            >
              <div className={styles.modeHeader}>
                <span className={styles.modeTitle}>🐾 Attend (동반자)</span>
                {currentMode === 'attend' && (
                  <span className={styles.checkIcon}>✔ 선택됨</span>
                )}
              </div>
              <p className={styles.modeDesc}>
                베라와 미우의 감성 케어, 위로, 다자간 티키타카 대화가 활성화되는 메인 동반자 모드입니다.
              </p>
            </button>

            <button
              className={`${styles.modeCard} ${
                currentMode === 'task' ? styles.modeCardActive : ''
              }`}
              onClick={() => handleSelectMode('task')}
              disabled={isUpdatingConfig || isLoadingConfig}
            >
              <div className={styles.modeHeader}>
                <span className={styles.modeTitle}>⚡ Task (업무)</span>
                {currentMode === 'task' && (
                  <span className={styles.checkIcon}>✔ 선택됨</span>
                )}
              </div>
              <p className={styles.modeDesc}>
                불필요한 만담을 최소화하고, 사실 기반의 명확한 분석과 도구 실행 중심의 집중 모드입니다.
              </p>
            </button>
          </div>

          <div style={{ marginTop: 'var(--spacing-3)' }}>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-main)' }}>
              활성 상주 페르소나 (Dual-Agent Architecture)
            </span>
            <div className={styles.personaList}>
              <div className={styles.personaItem}>
                <div className={`${styles.personaAvatar} ${styles.avatarVera}`}>베라</div>
                <div className={styles.personaInfo}>
                  <div className={styles.personaName}>
                    <span>베라 (Vera)</span>
                    <span style={{ fontSize: '10px', color: 'var(--color-vera)', border: '1px solid rgba(6, 182, 212, 0.3)', padding: '0 4px', borderRadius: 4 }}>
                      System 2 / 이성적 현실 케어
                    </span>
                  </div>
                  <span className={styles.personaRole}>
                    침착하고 논리적인 톤으로 상황을 정리하고 정확한 지침과 사실을 제공합니다.
                  </span>
                </div>
              </div>

              <div className={styles.personaItem}>
                <div className={`${styles.personaAvatar} ${styles.avatarMiu}`}>미우</div>
                <div className={styles.personaInfo}>
                  <div className={styles.personaName}>
                    <span>미우 (Miu)</span>
                    <span style={{ fontSize: '10px', color: 'var(--color-miu)', border: '1px solid rgba(245, 158, 11, 0.3)', padding: '0 4px', borderRadius: 4 }}>
                      System 1 / 정서적 힐링
                    </span>
                  </div>
                  <span className={styles.personaRole}>
                    사랑스럽고 발랄한 어조로 사용자 기분을 케어하며 활기찬 티키타카를 주도합니다.
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className={modalStyles.modalFooter}>
          <button
            className={styles.resetBtn}
            onClick={handleReset}
            disabled={isResettingConfig}
            title="기본값 초기화 (POST /api/v1/tars/config/reset)"
          >
            {isResettingConfig ? '초기화 중...' : '기본값으로 초기화 (POST /reset)'}
          </button>
          <button
            className={styles.resetBtn}
            style={{ backgroundColor: 'var(--color-primary)', color: '#ffffff', borderColor: 'var(--color-primary)' }}
            onClick={onClose}
          >
            확인
          </button>
        </div>
      </div>
    </div>
  );
};
