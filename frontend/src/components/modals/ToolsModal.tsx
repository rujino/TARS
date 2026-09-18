import React, { useState } from 'react';
import modalStyles from './Modal.module.css';
import styles from './ToolsModal.module.css';
import { useToolsQuery } from '@/queries/useToolsQuery';

interface ToolsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ToolsModal: React.FC<ToolsModalProps> = ({ isOpen, onClose }) => {
  const {
    servers,
    isLoadingServers,
    toggleTool,
    isTogglingTool,
    testServer,
    isTestingServer,
    googleCredentials,
    isLoadingGoogleCredentials,
    updateGoogleCredentials,
    isUpdatingGoogleCredentials,
    disconnectGoogle,
    isDisconnectingGoogle,
    getGoogleAuthUrl,
  } = useToolsQuery();

  const [testResults, setTestResults] = useState<Record<string, { latency_ms: number; status: string }>>({});
  const [customClientId, setCustomClientId] = useState('');
  const [customClientSecret, setCustomClientSecret] = useState('');
  const [isSavedCreds, setIsSavedCreds] = useState(false);

  if (!isOpen) return null;

  const handleToggle = async (toolName: string, currentActive: boolean) => {
    try {
      await toggleTool({
        toolName,
        payload: { active: !currentActive, enabled: !currentActive },
      });
    } catch (err: unknown) {
      alert('도구 토글 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleTestServer = async (serverId: string) => {
    try {
      const res = await testServer(serverId);
      setTestResults((prev) => ({
        ...prev,
        [serverId]: { latency_ms: res.latency_ms, status: res.status },
      }));
    } catch (err: unknown) {
      alert('서버 핑 테스트 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleSaveGoogleCredentials = async () => {
    try {
      await updateGoogleCredentials({
        client_id: customClientId.trim() || undefined,
        client_secret: customClientSecret.trim() || undefined,
      });
      setIsSavedCreds(true);
      setTimeout(() => setIsSavedCreds(false), 3000);
    } catch (err: unknown) {
      alert('Google 자격증명 저장 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleConnectGoogle = async () => {
    try {
      const { url } = await getGoogleAuthUrl();
      if (url) {
        window.location.href = url;
      }
    } catch (err: unknown) {
      alert('Google 인증 URL 발급 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleDisconnectGoogle = async () => {
    if (confirm('Google Workspace 연동을 해제하시겠습니까?')) {
      try {
        await disconnectGoogle();
      } catch (err: unknown) {
        alert('Google 연동 해제 실패: ' + (err instanceof Error ? err.message : String(err)));
      }
    }
  };

  return (
    <div className={modalStyles.backdrop} onClick={onClose}>
      <div className={modalStyles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={modalStyles.modalHeader}>
          <div className={modalStyles.modalTitle}>
            <span>⚙️</span>
            <span>도구 및 MCP 서버 연동 관리</span>
          </div>
          <button className={modalStyles.closeButton} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>

        <div className={modalStyles.modalBody}>
          {/* MCP & Builtin Tool Servers */}
          <div>
            <div className={styles.sectionTitle}>
              <span>등록된 도구 서버 (GET /api/v1/tools/servers)</span>
              {isLoadingServers && <span style={{ fontSize: '11px', color: 'var(--color-text-subtle)' }}>조회 중...</span>}
            </div>

            {servers.length > 0 ? (
              servers.map((server) => {
                const testRes = testResults[server.id];
                return (
                  <div key={server.id} className={styles.serverCard}>
                    <div className={styles.serverHeader}>
                      <div className={styles.serverBadgeRow}>
                        <span className={styles.serverName}>{server.name}</span>
                        <span className={styles.serverTypeBadge}>{server.type}</span>
                        <span
                          className={
                            server.status === 'connected'
                              ? styles.serverStatusConnected
                              : styles.serverStatusOffline
                          }
                        >
                          ● {server.status}
                        </span>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {testRes && (
                          <span style={{ fontSize: '11px', color: 'var(--color-vera)' }}>
                            {testRes.latency_ms.toFixed(1)}ms
                          </span>
                        )}
                        <button
                          className={styles.testBtn}
                          onClick={() => handleTestServer(server.id)}
                          disabled={isTestingServer}
                          title="POST /api/v1/tools/servers/{server_id}/test"
                        >
                          연결 테스트
                        </button>
                      </div>
                    </div>

                    {server.description && (
                      <p style={{ fontSize: '12px', color: 'var(--color-text-subtle)' }}>
                        {server.description}
                      </p>
                    )}

                    {/* Tools list */}
                    {server.tools && server.tools.length > 0 && (
                      <div className={styles.toolList}>
                        {server.tools.map((tool) => (
                          <div key={tool.name} className={styles.toolItem}>
                            <div className={styles.toolItemInfo}>
                              <span className={styles.toolItemName}>{tool.name}</span>
                              <span className={styles.toolItemDesc}>{tool.description}</span>
                            </div>
                            <label className={styles.toggleSwitch} title="PATCH /api/v1/tools/{tool_name}/toggle">
                              <input
                                type="checkbox"
                                checked={tool.active}
                                disabled={isTogglingTool}
                                onChange={() => handleToggle(tool.name, tool.active)}
                              />
                              <span className={styles.slider} />
                            </label>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div style={{ padding: 'var(--spacing-4)', textAlign: 'center', color: 'var(--color-text-subtle)' }}>
                등록된 도구 서버가 없습니다.
              </div>
            )}
          </div>

          {/* Google Workspace Integration */}
          <div>
            <div className={styles.sectionTitle}>
              <span>Google Workspace 연동 관리 (/tools/auth/google)</span>
              {isLoadingGoogleCredentials && <span style={{ fontSize: '11px', color: 'var(--color-text-subtle)' }}>조회 중...</span>}
            </div>

            <div className={styles.googleCard}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: '13px' }}>연동 상태:</span>
                  <span
                    style={{
                      fontSize: '12px',
                      color: googleCredentials?.is_linked ? 'var(--color-success)' : 'var(--color-text-subtle)',
                      fontWeight: 600,
                    }}
                  >
                    {googleCredentials?.is_linked
                      ? `연동됨 (${googleCredentials.account_email || 'Google 계정'})`
                      : '미연동'}
                  </span>
                </div>

                <div className={styles.googleActionRow}>
                  {googleCredentials?.is_linked ? (
                    <button
                      className={styles.googleDisconnectBtn}
                      onClick={handleDisconnectGoogle}
                      disabled={isDisconnectingGoogle}
                      title="POST /api/v1/tools/auth/google/disconnect"
                    >
                      {isDisconnectingGoogle ? '해제 중...' : '연동 해제 (Disconnect)'}
                    </button>
                  ) : (
                    <button
                      className={styles.googleConnectBtn}
                      onClick={handleConnectGoogle}
                      title="GET /api/v1/tools/auth/google/url"
                    >
                      <span>Google 계정 연동 시작</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <line x1="5" y1="12" x2="19" y2="12" />
                        <polyline points="12 5 19 12 12 19" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {/* Custom Client ID / Secret */}
              <div className={styles.googleInputs}>
                <div className={styles.googleInputRow}>
                  <label style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                    Google OAuth2 Client ID (설정된 값: {googleCredentials?.client_id || '없음'})
                  </label>
                  <input
                    className={styles.googleInput}
                    placeholder="새 Client ID 입력"
                    value={customClientId}
                    onChange={(e) => setCustomClientId(e.target.value)}
                  />
                </div>
                <div className={styles.googleInputRow}>
                  <label style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                    Google OAuth2 Client Secret (등록 여부: {googleCredentials?.has_client_secret ? '등록됨' : '없음'})
                  </label>
                  <input
                    className={styles.googleInput}
                    type="password"
                    placeholder="새 Client Secret 입력"
                    value={customClientSecret}
                    onChange={(e) => setCustomClientSecret(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
                  {isSavedCreds && <span style={{ fontSize: '11px', color: 'var(--color-success)' }}>저장 완료!</span>}
                  <button
                    className={styles.testBtn}
                    onClick={handleSaveGoogleCredentials}
                    disabled={isUpdatingGoogleCredentials}
                    title="POST /api/v1/tools/auth/google/credentials"
                  >
                    {isUpdatingGoogleCredentials ? '저장 중...' : '자격증명 저장'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className={modalStyles.modalFooter}>
          <button
            className={styles.testBtn}
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
