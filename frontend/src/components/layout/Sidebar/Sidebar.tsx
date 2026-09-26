import React from 'react';
import styles from './Sidebar.module.css';
import { useSessionStore } from '@/stores/useSessionStore';
import { useChatQuery } from '@/queries/useChatQuery';
import { useAuthQuery } from '@/queries/useAuthQuery';
import { useUIStore } from '@/stores/useUIStore';
import type { ChatSessionItem } from '@/types/chat.types';

const DATE_GROUPS = ['Today', 'Yesterday', 'Past 7 days', 'Past 30 days', 'Older'] as const;

export const Sidebar: React.FC = () => {
  const isSidebarOpen = useSessionStore((state) => state.isSidebarOpen);
  const setSidebarOpen = useSessionStore((state) => state.setSidebarOpen);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const setActiveSession = useSessionStore((state) => state.setActiveSession);
  const openModal = useUIStore((state) => state.openModal);

  const { sessionGroups, deleteSession, isDeletingSession, deleteAllSessions, isDeletingAllSessions } = useChatQuery(activeSessionId);
  const { user, isLoggedIn, logout } = useAuthQuery();

  const handleNewChat = () => {
    if (activeSessionId) {
      const proceed = confirm(
        '⚠️ 새 대화를 시작하시겠습니까?\n\n현재 일일 대화와의 연속성이 분리되며 새로운 대화 세션이 생성됩니다.\n(이전 대화는 사이드바 기록에서 언제든 다시 확인할 수 있습니다.)'
      );
      if (!proceed) return;
    }
    setActiveSession(null, null);
    setSidebarOpen(false);
  };

  const handleSelectSession = (sessionId: string, title?: string | null) => {
    setActiveSession(sessionId, title);
    setSidebarOpen(false);
  };

  const handleDeleteAllSessions = async () => {
    if (confirm('⚠️ 정말 모든 대화 세션을 초기화(삭제)하시겠습니까?\n이 작업은 DB의 모든 대화 기록을 완전히 삭제하며 되돌릴 수 없습니다.')) {
      try {
        await deleteAllSessions();
        setActiveSession(null, null);
      } catch (err) {
        alert('전체 세션 삭제에 실패했습니다: ' + (err instanceof Error ? err.message : String(err)));
      }
    }
  };

  const handleDeleteSession = async (e: React.MouseEvent, session: ChatSessionItem) => {
    e.stopPropagation();
    if (confirm(`'${session.title || '대화 세션'}'을(를) 삭제하시겠습니까?`)) {
      try {
        await deleteSession(session.id);
        if (activeSessionId === session.id) {
          setActiveSession(null, null);
        }
      } catch (err) {
        alert('세션 삭제에 실패했습니다: ' + (err instanceof Error ? err.message : String(err)));
      }
    }
  };

  const formatTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' });
    } catch {
      return '';
    }
  };

  const hasAnySessions = DATE_GROUPS.some(
    (g) => sessionGroups[g] && sessionGroups[g].length > 0
  );

  return (
    <>
      {/* 1. Backdrop Overlay */}
      <div
        className={`${styles.backdrop} ${isSidebarOpen ? styles.backdropVisible : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      {/* 2. Off-canvas Drawer Body */}
      <aside
        className={`${styles.sidebar} ${isSidebarOpen ? styles.sidebarOpen : ''}`}
        aria-label="대화 기록 사이드바"
      >
        <div className={styles.topAction}>
          <button className={styles.newChatButton} onClick={handleNewChat}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            <span>새 대화 시작</span>
          </button>

          <button
            className={styles.closeButton}
            onClick={() => setSidebarOpen(false)}
            aria-label="사이드바 닫기"
            title="사이드바 닫기"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className={styles.timelineContainer}>
          {hasAnySessions ? (
            DATE_GROUPS.map((groupName) => {
              const items = sessionGroups[groupName];
              if (!items || items.length === 0) return null;

              return (
                <div key={groupName} className={styles.dateGroup}>
                  <div className={styles.groupLabel}>{groupName}</div>
                  {items.map((sess) => {
                    const isActive = activeSessionId === sess.id;
                    return (
                      <div
                        key={sess.id}
                        className={`${styles.sessionItem} ${isActive ? styles.sessionItemActive : ''}`}
                        onClick={() => handleSelectSession(sess.id, sess.title)}
                      >
                        <div className={styles.sessionContent}>
                          <span className={styles.sessionTitle}>
                            {sess.title || '새 대화'}
                          </span>
                          <div className={styles.sessionMeta}>
                            <span>{formatTime(sess.last_active_at)}</span>
                            {sess.message_count > 0 && (
                              <span className={styles.messageCountBadge}>
                                {sess.message_count}
                              </span>
                            )}
                          </div>
                        </div>

                      <button
                        className={styles.deleteButton}
                        onClick={(e) => handleDeleteSession(e, sess)}
                        disabled={isDeletingSession}
                        title="대화 세션 삭제 (/api/v1/chat/sessions/{session_id})"
                        aria-label="대화 세션 삭제"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="3 6 5 6 21 6" />
                          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        </svg>
                      </button>
                    </div>
                  );
                })}
              </div>
            );
          })
        ) : (
          <div className={styles.emptyTimeline}>
            <span>대화 기록이 없습니다.</span>
          </div>
        )}

        {hasAnySessions && (
          <div style={{ padding: '0.5rem 0.75rem', marginTop: 'auto' }}>
            <button
              onClick={handleDeleteAllSessions}
              disabled={isDeletingAllSessions}
              style={{
                width: '100%',
                padding: '0.4rem 0.5rem',
                fontSize: '0.75rem',
                color: 'var(--color-danger, #ef4444)',
                background: 'transparent',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.35rem',
              }}
              title="현재 사용자의 전체 대화 세션 및 메시지 영구 삭제"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
              <span>{isDeletingAllSessions ? '초기화 중...' : '대화 기록 전체 초기화'}</span>
            </button>
          </div>
        )}
      </div>

      <div className={styles.bottomProfile}>
        {isLoggedIn && user ? (
          <>
            <div className={styles.userCard} onClick={() => openModal('auth')}>
              <div className={styles.userAvatar}>
                {user.username.charAt(0).toUpperCase()}
              </div>
              <div className={styles.userDetails}>
                <span className={styles.userName}>{user.username}</span>
                <span className={styles.userStatus}>온라인</span>
              </div>
            </div>
            <button
              className={styles.logoutIconBtn}
              onClick={logout}
              title="로그아웃"
              aria-label="로그아웃"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
            </button>
          </>
        ) : (
          <button
            className={styles.newChatButton}
            style={{ backgroundColor: 'var(--color-surface-hover)' }}
            onClick={() => openModal('auth')}
          >
            <span>로그인 / 가입</span>
          </button>
        )}
      </div>
    </aside>
  </>
);
};
