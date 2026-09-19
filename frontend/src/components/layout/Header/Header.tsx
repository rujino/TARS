import React from 'react';
import styles from './Header.module.css';
import { useSessionStore } from '@/stores/useSessionStore';
import { useUIStore } from '@/stores/useUIStore';
import { usePersonaQuery } from '@/queries/usePersonaQuery';
import { useSystemQuery } from '@/queries/useSystemQuery';
import { useAuthQuery } from '@/queries/useAuthQuery';

export const Header: React.FC = () => {
  const toggleSidebar = useSessionStore((state) => state.toggleSidebar);
  const isSidebarOpen = useSessionStore((state) => state.isSidebarOpen);
  const openModal = useUIStore((state) => state.openModal);

  const { config } = usePersonaQuery();
  const { readiness, isReady } = useSystemQuery();
  const { user, isLoggedIn } = useAuthQuery();

  const modeLabel =
    config?.mode === 'task'
      ? '⚡ Task (업무 모드)'
      : '🐾 Attend (동반자 모드)';

  return (
    <header className={styles.header}>
      <div className={styles.leftSection}>
        <button
          className={styles.iconButton}
          onClick={toggleSidebar}
          aria-label={isSidebarOpen ? '사이드바 접기' : '사이드바 열기'}
          title={isSidebarOpen ? '사이드바 접기' : '사이드바 열기'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <div className={styles.logo}>
          <span>TARS</span>
          <span className={styles.logoBadge}>AI</span>
        </div>

        {/* TARS Persona Operational Mode */}
        <button
          className={styles.modeBadge}
          onClick={() => openModal('persona')}
          title="TARS 페르소나 설정 및 운영 모드 변경 (/api/v1/tars/config)"
        >
          <span>{modeLabel}</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      </div>

      <div className={styles.rightSection}>
        {/* System Health Readiness Indicator */}
        <button
          className={styles.healthIndicator}
          onClick={() => openModal('system')}
          title="시스템 헬스 및 메트릭 모니터링 (/health, /health/readiness, /metrics)"
        >
          <span
            className={`${styles.statusDot} ${
              isReady ? styles.statusDotReady : styles.statusDotDegraded
            }`}
          />
          <span>{readiness?.status === 'ready' ? '시스템 정상' : '상태 점검'}</span>
        </button>

        {/* Tools & MCP Servers Management */}
        <button
          className={styles.navButton}
          onClick={() => openModal('tools')}
          title="도구 및 MCP 서버 연동 관리 (/api/v1/tools/servers)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
          <span>도구/MCP</span>
        </button>

        {/* User Auth Profile Badge */}
        {isLoggedIn && user ? (
          <button
            className={styles.userBadge}
            onClick={() => openModal('auth')}
            title="사용자 정보 및 로그아웃"
          >
            <div className={styles.avatarCircle}>
              {user.username.charAt(0).toUpperCase()}
            </div>
            <span>{user.username}</span>
          </button>
        ) : (
          <button
            className={styles.navButton}
            onClick={() => openModal('auth')}
            title="로그인 또는 회원가입"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            <span>로그인</span>
          </button>
        )}
      </div>
    </header>
  );
};
