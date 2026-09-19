import React from 'react';
import modalStyles from './Modal.module.css';
import styles from './SystemStatusModal.module.css';
import { useSystemQuery } from '@/queries/useSystemQuery';

interface SystemStatusModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const SystemStatusModal: React.FC<SystemStatusModalProps> = ({ isOpen, onClose }) => {
  const {
    health,
    liveness,
    readiness,
    refetchReadiness,
    refetchLiveness,
    refetchHealth,
    metrics,
    isLoadingMetrics,
    refetchMetrics,
  } = useSystemQuery();

  if (!isOpen) return null;

  const handleRefreshAll = () => {
    refetchHealth();
    refetchLiveness();
    refetchReadiness();
    refetchMetrics();
  };

  return (
    <div className={modalStyles.backdrop} onClick={onClose}>
      <div className={modalStyles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={modalStyles.modalHeader}>
          <div className={modalStyles.modalTitle}>
            <span>🩺</span>
            <span>시스템 헬스 & 텔레메트리 모니터링</span>
          </div>
          <button className={modalStyles.closeButton} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div className={modalStyles.modalBody}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text-main)' }}>
              Kubernetes 및 컨테이너 프로브 상태
            </span>
            <button className={styles.refreshBtn} onClick={handleRefreshAll}>
              새로고침
            </button>
          </div>

          <div className={styles.cardGrid}>
            {/* Liveness Check */}
            <div className={styles.probeCard}>
              <div className={styles.probeHeader}>
                <span className={styles.probeTitle}>Liveness (/health/liveness)</span>
                <span
                  className={
                    health?.status === 'ok' || liveness?.status === 'ok'
                      ? styles.statusBadgeReady
                      : styles.statusBadgeDegraded
                  }
                >
                  {health?.status === 'ok' || liveness?.status === 'ok' ? 'HEALTHY' : 'DOWN'}
                </span>
              </div>
              <div className={styles.probeDetails}>
                <div>기본 프로세스 상태: {health?.status ?? '확인 중'}</div>
                <div>엔진 식별자: {health?.app ?? 'TARS'}</div>
              </div>
            </div>

            {/* Deep Readiness Check */}
            <div className={styles.probeCard}>
              <div className={styles.probeHeader}>
                <span className={styles.probeTitle}>Readiness (/health/readiness)</span>
                <span
                  className={
                    readiness?.status === 'ready'
                      ? styles.statusBadgeReady
                      : styles.statusBadgeDegraded
                  }
                >
                  {readiness?.status?.toUpperCase() ?? 'CHECKING'}
                </span>
              </div>
              <div className={styles.probeDetails}>
                <div>데이터베이스: {readiness?.database ?? readiness?.checks?.database ?? '점검 중'}</div>
                <div>스토리지 (SeaweedFS): {readiness?.storage ?? readiness?.checks?.storage ?? '점검 중'}</div>
              </div>
            </div>
          </div>

          {/* Prometheus Metrics */}
          <div style={{ marginTop: 'var(--spacing-2)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-main)' }}>
                Prometheus 텔레메트리 메트릭 (GET /metrics)
              </span>
              <button
                className={styles.refreshBtn}
                onClick={() => refetchMetrics()}
                disabled={isLoadingMetrics}
              >
                {isLoadingMetrics ? '수집 중...' : '메트릭 조회'}
              </button>
            </div>

            {metrics ? (
              <div className={styles.metricsBox}>
                {metrics
                  .split('\n')
                  .filter((line) => line && !line.startsWith('#'))
                  .slice(0, 30)
                  .join('\n')}
              </div>
            ) : (
              <div
                style={{
                  padding: 'var(--spacing-3)',
                  backgroundColor: 'var(--color-bg-primary)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '11px',
                  color: 'var(--color-text-subtle)',
                  textAlign: 'center',
                }}
              >
                '메트릭 조회' 버튼을 눌러 실시간 Prometheus 카운터를 확인하세요.
              </div>
            )}
          </div>
        </div>

        <div className={modalStyles.modalFooter}>
          <button
            className={styles.refreshBtn}
            style={{ backgroundColor: 'var(--color-primary)', color: '#ffffff', borderColor: 'var(--color-primary)', padding: '6px 14px' }}
            onClick={onClose}
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
};
