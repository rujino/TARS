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
  const isTtsEnabled = useUIStore((state) => state.isTtsEnabled);
  const toggleTts = useUIStore((state) => state.toggleTts);

  const { readiness, isReady } = useSystemQuery();
  const { user, isLoggedIn } = useAuthQuery();

  return (
    <header className={styles.header}>
      <div className={styles.leftSection}>
        <button
          className={styles.iconButton}
          onClick={toggleSidebar}
          aria-label={isSidebarOpen ? '사이드바 닫기' : '사이드바 열기'}
          title={isSidebarOpen ? '사이드바 닫기' : '사이드바 열기'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        <div className={styles.logo}>
          <span>TARS</span>
        </div>

        {/* System Health Dot */}
        <button
          className={styles.healthIndicator}
          onClick={() => openModal('system')}
          title={readiness?.status === 'ready' ? '시스템 정상 작동 중' : '시스템 상태 확인 필요'}
          aria-label="시스템 헬스체크"
        >
          <span
            className={`${styles.statusDot} ${
              isReady ? styles.statusDotReady : styles.statusDotDegraded
            }`}
          />
        </button>
      </div>

      <div className={styles.rightSection}>
        {/* Gemini-TTS On/Off Toggle Button */}
        <button
          className={`${styles.ttsToggle} ${isTtsEnabled ? styles.ttsToggleActive : ''}`}
          onClick={toggleTts}
          title={isTtsEnabled ? 'TTS 음성 활성화됨 (gemini-tts 준비)' : 'TTS 음성 꺼짐 (클릭 시 켜기)'}
          aria-label={isTtsEnabled ? 'TTS 끄기' : 'TTS 켜기'}
        >
          <span>{isTtsEnabled ? '🔊 TTS ON' : '🔇 TTS OFF'}</span>
        </button>

        {/* Tools & MCP Servers Management */}
        <button
          className={styles.navButton}
          onClick={() => openModal('tools')}
          title="도구 및 MCP 서버 연동 관리"
          aria-label="도구 및 MCP 연동 관리"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
          </svg>
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
          </button>
        )}
      </div>
    </header>
  );
};
