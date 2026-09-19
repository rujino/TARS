import React, { useState } from 'react';
import modalStyles from './Modal.module.css';
import styles from './AuthModal.module.css';
import { useAuthQuery } from '@/queries/useAuthQuery';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ isOpen, onClose }) => {
  const {
    user,
    isLoggedIn,
    login,
    isLoggingIn,
    signup,
    isSigningUp,
    issueWsTicket,
    logout,
  } = useAuthQuery();

  const [activeTab, setActiveTab] = useState<'login' | 'signup'>(isLoggedIn ? 'login' : 'login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [ticketResult, setTicketResult] = useState<{ ticket: string; expires_in: number } | null>(null);
  const [isIssuingTicket, setIsIssuingTicket] = useState(false);

  if (!isOpen) return null;

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await login({ username, password });
      onClose();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || '로그인에 실패했습니다. 계정 정보를 확인해주세요.');
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await signup({ username, email, password });
      onClose();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || '회원가입에 실패했습니다. 입력값을 확인해주세요.');
    }
  };

  const handleTestTicket = async () => {
    try {
      setIsIssuingTicket(true);
      const res = await issueWsTicket();
      setTicketResult(res);
    } catch (err: unknown) {
      alert('티켓 발급 실패: ' + (err instanceof Error ? err.message : String(err)));
    } finally {
      setIsIssuingTicket(false);
    }
  };

  return (
    <div className={modalStyles.backdrop} onClick={onClose}>
      <div className={modalStyles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={modalStyles.modalHeader}>
          <div className={modalStyles.modalTitle}>
            <span>👤</span>
            <span>{isLoggedIn ? '사용자 프로필 & 인증' : 'TARS 계정 인증'}</span>
          </div>
          <button className={modalStyles.closeButton} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div className={modalStyles.modalBody}>
          {isLoggedIn && user ? (
            <>
              <div className={styles.profileCard}>
                <div className={styles.profileRow}>
                  <span className={styles.profileKey}>사용자명 (Username)</span>
                  <span className={styles.profileVal}>{user.username}</span>
                </div>
                <div className={styles.profileRow}>
                  <span className={styles.profileKey}>이메일 (Email)</span>
                  <span className={styles.profileVal}>{user.email || '미등록'}</span>
                </div>
                <div className={styles.profileRow}>
                  <span className={styles.profileKey}>사용자 고유 ID</span>
                  <span className={styles.profileVal}>{user.id}</span>
                </div>
                <div className={styles.profileRow}>
                  <span className={styles.profileKey}>계정 상태</span>
                  <span className={styles.profileVal} style={{ color: 'var(--color-success)' }}>
                    {user.is_active ? '정상 활성' : '비활성'}
                  </span>
                </div>
              </div>

              {/* WebSocket 단기 1회용 티켓 발급 테스트 (/api/v1/auth/ws-ticket) */}
              <div className={styles.ticketBox}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--color-text-main)' }}>
                    WebSocket 1회용 단기 티켓 테스트
                  </span>
                  <button
                    className={styles.submitBtn}
                    style={{ margin: 0, padding: '4px 10px', fontSize: '11px' }}
                    onClick={handleTestTicket}
                    disabled={isIssuingTicket}
                  >
                    {isIssuingTicket ? '발급 중...' : 'POST /api/v1/auth/ws-ticket'}
                  </button>
                </div>
                <span style={{ color: 'var(--color-text-subtle)', fontSize: '11px' }}>
                  실시간 WebSocket 핸드셰이크 시 URL 토큰 노출을 방지하기 위해 30초 유효 1회용 티켓을 발급합니다.
                </span>
                {ticketResult && (
                  <div>
                    <div style={{ marginBottom: 4 }}>티켓 발급 성공 (유효기간 {ticketResult.expires_in}초):</div>
                    <div className={styles.ticketValue}>{ticketResult.ticket}</div>
                  </div>
                )}
              </div>

              <button
                className={styles.submitBtn}
                style={{ backgroundColor: 'var(--color-danger)' }}
                onClick={() => {
                  logout();
                  onClose();
                }}
              >
                로그아웃
              </button>
            </>
          ) : (
            <>
              <div className={styles.tabs}>
                <button
                  className={`${styles.tabButton} ${
                    activeTab === 'login' ? styles.tabButtonActive : ''
                  }`}
                  onClick={() => {
                    setActiveTab('login');
                    setError(null);
                  }}
                >
                  로그인 (POST /auth/login)
                </button>
                <button
                  className={`${styles.tabButton} ${
                    activeTab === 'signup' ? styles.tabButtonActive : ''
                  }`}
                  onClick={() => {
                    setActiveTab('signup');
                    setError(null);
                  }}
                >
                  회원가입 (POST /auth/signup)
                </button>
              </div>

              {error && <div className={styles.errorMessage}>{error}</div>}

              {activeTab === 'login' ? (
                <form className={styles.form} onSubmit={handleLogin}>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>아이디 (Username)</label>
                    <input
                      className={styles.input}
                      type="text"
                      required
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="아이디를 입력하세요"
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>비밀번호 (Password)</label>
                    <input
                      className={styles.input}
                      type="password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="비밀번호를 입력하세요"
                    />
                  </div>
                  <button className={styles.submitBtn} type="submit" disabled={isLoggingIn}>
                    {isLoggingIn ? '로그인 중...' : '로그인'}
                  </button>
                </form>
              ) : (
                <form className={styles.form} onSubmit={handleSignup}>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>아이디 (Username, 3~50자)</label>
                    <input
                      className={styles.input}
                      type="text"
                      required
                      minLength={3}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="아이디를 입력하세요"
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>이메일 (Email)</label>
                    <input
                      className={styles.input}
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="example@tars.ai"
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>비밀번호 (Password, 8자 이상)</label>
                    <input
                      className={styles.input}
                      type="password"
                      required
                      minLength={8}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="비밀번호를 입력하세요"
                    />
                  </div>
                  <button className={styles.submitBtn} type="submit" disabled={isSigningUp}>
                    {isSigningUp ? '가입 중...' : '계정 생성 및 로그인'}
                  </button>
                </form>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
