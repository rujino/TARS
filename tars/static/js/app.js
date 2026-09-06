/**
 * TARS SPA Main Application Controller
 * Handles:
 * - Routing between AuthView and ChatView
 * - Real-time dual streaming integration
 * - On-Device TTS engine linkage
 * - Persona controls (Humor / Honesty / Mode) bidirectional sync
 * - Service Worker registration & PWA lifecycle
 */
(function () {
  'use strict';

  // --- Global Services ---
  const api = new TARSApiClient();
  const tts = new TARSTTSEngine();
  let streamClient = null;

  // --- State Variables ---
  let activeTab = 'login'; // 'login' | 'signup'
  let isStreaming = false;
  let currentTarsBubble = null;
  let currentTarsText = '';
  let configDebounceTimer = null;

  // --- Tool & MCP State (G5) ---
  const toolState = {
    servers: [],
    expandedServerIds: new Set(['google_workspace']),
    updatingTools: new Set(),
    activeModal: null
  };
  let previouslyActiveElement = null;

  // --- DOM Elements ---
  const dom = {
    // Views
    authView: document.getElementById('auth-view'),
    chatView: document.getElementById('chat-view'),

    // Auth
    tabLogin: document.getElementById('tab-login'),
    tabSignup: document.getElementById('tab-signup'),
    formLogin: document.getElementById('form-login'),
    formSignup: document.getElementById('form-signup'),
    authError: document.getElementById('auth-error'),
    loginUsername: document.getElementById('login-username'),
    loginPassword: document.getElementById('login-password'),
    signupUsername: document.getElementById('signup-username'),
    signupEmail: document.getElementById('signup-email'),
    signupPassword: document.getElementById('signup-password'),

    // Header
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    modeBadge: document.getElementById('mode-badge'),
    btnTts: document.getElementById('btn-tts'),
    btnConfig: document.getElementById('btn-config'),
    btnLogout: document.getElementById('btn-logout'),

    // Sidebar & Persona Controls
    sidebar: document.getElementById('sidebar'),
    userDisplayName: document.getElementById('user-display-name'),
    humorSlider: document.getElementById('humor-slider'),
    humorVal: document.getElementById('humor-val'),
    honestySlider: document.getElementById('honesty-slider'),
    honestyVal: document.getElementById('honesty-val'),
    modeCompanion: document.getElementById('mode-companion'),
    modeWork: document.getElementById('mode-work'),
    btnResetConfig: document.getElementById('btn-reset-config'),

    // Tools & MCP Management (G5)
    toolsServerList: document.getElementById('tools-server-list'),
    toolsGlobalBadge: document.getElementById('tools-global-badge'),
    btnRefreshTools: document.getElementById('btn-refresh-tools'),

    // Modal (G5)
    modalOverlay: document.getElementById('hud-modal-overlay'),
    modalCard: document.getElementById('hud-modal-card'),
    modalTitle: document.getElementById('modal-title'),
    modalBodyContent: document.getElementById('modal-body-content'),
    modalCloseBtn: document.getElementById('modal-close-btn'),
    modalFooter: document.getElementById('modal-footer'),
    modalBtnCancel: document.getElementById('modal-btn-cancel'),

    // Toast Container (G5)
    toastContainer: document.getElementById('hud-toast-container'),

    // Chat
    messagesContainer: document.getElementById('messages-container'),
    chatInput: document.getElementById('chat-input'),
    sendBtn: document.getElementById('send-btn')
  };

  // --- Service Worker Registration ---
  function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker
          .register('/sw.js')
          .then((reg) => {
            console.log('[PWA] Service Worker registered with scope:', reg.scope);
          })
          .catch((err) => {
            console.warn('[PWA] Service Worker registration failed:', err);
          });
      });
    }
  }

  // --- View Switcher ---
  function showView(viewName) {
    if (viewName === 'chat') {
      dom.authView.classList.remove('active');
      dom.chatView.classList.add('active');
      dom.btnTts.style.display = 'inline-flex';
      dom.btnConfig.style.display = 'inline-flex';
      dom.btnLogout.style.display = 'inline-flex';
      if (dom.modeBadge) dom.modeBadge.style.display = 'inline-block';
      dom.chatInput.focus();
    } else {
      dom.chatView.classList.remove('active');
      dom.authView.classList.add('active');
      dom.btnTts.style.display = 'none';
      dom.btnConfig.style.display = 'none';
      dom.btnLogout.style.display = 'none';
      if (dom.modeBadge) dom.modeBadge.style.display = 'none';
      if (streamClient) streamClient.disconnect();
      tts.stop();
    }
  }

  // --- Auth UI Helpers ---
  function setAuthError(msg) {
    if (msg) {
      dom.authError.textContent = msg;
      dom.authError.classList.add('visible');
    } else {
      dom.authError.textContent = '';
      dom.authError.classList.remove('visible');
    }
  }

  function switchAuthTab(tab) {
    activeTab = tab;
    setAuthError('');
    if (tab === 'login') {
      dom.tabLogin.classList.add('active');
      dom.tabSignup.classList.remove('active');
      dom.formLogin.style.display = 'flex';
      dom.formSignup.style.display = 'none';
    } else {
      dom.tabSignup.classList.add('active');
      dom.tabLogin.classList.remove('active');
      dom.formSignup.style.display = 'flex';
      dom.formLogin.style.display = 'none';
    }
  }

  // --- Markdown Parser Helper ---
  function renderMarkdown(text) {
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
      try {
        const rawHtml = marked.parse ? marked.parse(text) : marked(text);
        return DOMPurify.sanitize(rawHtml);
      } catch (err) {
        console.warn('[Markdown] Render error:', err);
      }
    }
    // Fallback simple line break
    return text.replace(/\n/g, '<br>');
  }

  function scrollToBottom() {
    dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;
  }

  // --- Append Messages to UI ---
  function appendUserMessage(text) {
    const item = document.createElement('div');
    item.className = 'message-item user';

    const header = document.createElement('div');
    header.className = 'message-header';
    header.innerHTML = '<span>USER</span>';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;

    item.appendChild(header);
    item.appendChild(bubble);
    dom.messagesContainer.appendChild(item);
    scrollToBottom();
  }

  function createTarsMessagePlaceholder() {
    const item = document.createElement('div');
    item.className = 'message-item tars';

    const header = document.createElement('div');
    header.className = 'message-header';
    header.innerHTML = '<span>TARS // AI</span>';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.innerHTML = '<span class="tars-cursor"></span>';

    item.appendChild(header);
    item.appendChild(bubble);
    dom.messagesContainer.appendChild(item);
    scrollToBottom();

    return bubble;
  }

  // --- Persona Configuration Sync ---
  async function loadUserConfig() {
    try {
      const config = await api.getConfig();
      applyConfigToUI(config);
    } catch (err) {
      console.warn('[Config] Failed to load config:', err);
    }
  }

  function applyConfigToUI(config) {
    const humorPct = Math.round((config.humor_level ?? 0.90) * 100);
    const honestyPct = Math.round((config.honesty_level ?? 0.95) * 100);
    const mode = config.mode || 'companion';

    dom.humorSlider.value = humorPct;
    dom.humorVal.textContent = `${humorPct}%`;

    dom.honestySlider.value = honestyPct;
    dom.honestyVal.textContent = `${honestyPct}%`;

    if (mode === 'work') {
      dom.modeWork.classList.add('active');
      dom.modeCompanion.classList.remove('active');
      if (dom.modeBadge) dom.modeBadge.textContent = '[ MODE: WORK ]';
    } else {
      dom.modeCompanion.classList.add('active');
      dom.modeWork.classList.remove('active');
      if (dom.modeBadge) dom.modeBadge.textContent = '[ MODE: COMPANION ]';
    }
  }

  function scheduleConfigUpdate() {
    clearTimeout(configDebounceTimer);
    configDebounceTimer = setTimeout(async () => {
      const humor = parseInt(dom.humorSlider.value, 10) / 100.0;
      const honesty = parseInt(dom.honestySlider.value, 10) / 100.0;
      try {
        const updated = await api.updateConfig({
          humor_level: humor,
          honesty_level: honesty
        });
        applyConfigToUI(updated);
      } catch (err) {
        console.warn('[Config] Update failed:', err);
      }
    }, 300);
  }

  // --- Stream Client Initialization ---
  function initStreamClient() {
    streamClient = new TARSStreamClient(api, {
      onStart: (sessionId) => {
        isStreaming = true;
        dom.sendBtn.disabled = true;
        currentTarsText = '';
        currentTarsBubble = createTarsMessagePlaceholder();
      },
      onToken: (chunk) => {
        if (!chunk) return;
        currentTarsText += chunk;
        if (currentTarsBubble) {
          currentTarsBubble.innerHTML = renderMarkdown(currentTarsText) + '<span class="tars-cursor"></span>';
          scrollToBottom();
        }
        tts.pushToken(chunk);
      },
      onEnd: (fullText) => {
        isStreaming = false;
        dom.sendBtn.disabled = false;
        if (currentTarsBubble) {
          const finalText = fullText || currentTarsText;
          currentTarsBubble.innerHTML = renderMarkdown(finalText);
          scrollToBottom();
        }
        tts.flush();
        dom.chatInput.focus();
      },
      onError: (errorMsg) => {
        isStreaming = false;
        dom.sendBtn.disabled = false;
        if (currentTarsBubble) {
          currentTarsBubble.innerHTML =
            renderMarkdown(currentTarsText) +
            `<div style="color: var(--tars-red); margin-top: 8px; font-size: 12px;">[ERROR: ${escapeHtml(errorMsg)}]</div>`;
          scrollToBottom();
        }
        tts.stop();
        dom.chatInput.focus();
      },
      onStatusChange: (status) => {
        dom.statusText.textContent = status;
        dom.statusDot.className = 'status-dot';
        if (status === 'ONLINE') {
          dom.statusDot.classList.add('online');
        } else if (status.startsWith('CONNECTING') || status.startsWith('RECONNECTING')) {
          dom.statusDot.classList.add('connecting');
        } else {
          dom.statusDot.classList.add('offline');
        }
      }
    });

    streamClient.connectWebSocket();
  }

  // --- Chat Submission ---
  async function handleSendMessage() {
    const text = dom.chatInput.value.trim();
    if (!text || isStreaming) return;

    dom.chatInput.value = '';
    dom.chatInput.style.height = 'auto';

    appendUserMessage(text);

    if (streamClient) {
      await streamClient.sendMessage(text);
    }
  }

  // --- HTML Escaping & Sanitization (G5 Remediation) ---
  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // --- HUD Notifications (Toasts) ---
  function showNotification(message, type = 'info') {
    if (!dom.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `hud-toast ${type}`;
    let icon = 'ℹ';
    if (type === 'success') icon = '✓';
    else if (type === 'error') icon = '⚠';
    else if (type === 'warning') icon = '⚡';

    const iconSpan = document.createElement('span');
    iconSpan.style.fontWeight = '700';
    iconSpan.textContent = `[ ${icon} ]`;

    const msgSpan = document.createElement('span');
    msgSpan.textContent = String(message ?? '');

    toast.appendChild(iconSpan);
    toast.appendChild(msgSpan);
    dom.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 250);
    }, 4000);
  }

  // --- HUD Modal Dialog Management (G5) ---
  function openModal(title, renderContentFn, footerButtons = null) {
    if (!dom.modalOverlay) return;
    previouslyActiveElement = document.activeElement;
    dom.modalTitle.textContent = title;
    dom.modalBodyContent.innerHTML = '';
    renderContentFn(dom.modalBodyContent);

    if (footerButtons && footerButtons.length > 0) {
      dom.modalFooter.innerHTML = '';
      footerButtons.forEach((btn) => dom.modalFooter.appendChild(btn));
    } else {
      dom.modalFooter.innerHTML = '<button id="modal-btn-cancel" class="hud-btn">DISMISS</button>';
      const cancelBtn = dom.modalFooter.querySelector('#modal-btn-cancel');
      if (cancelBtn) cancelBtn.addEventListener('click', closeModal);
    }

    dom.modalOverlay.style.display = 'flex';

    // Focus management: focus close button or first interactive element
    requestAnimationFrame(() => {
      if (dom.modalCloseBtn) {
        dom.modalCloseBtn.focus();
      } else if (dom.modalCard) {
        const firstFocusable = dom.modalCard.querySelector('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
        if (firstFocusable) firstFocusable.focus();
      }
    });
  }

  function closeModal() {
    if (!dom.modalOverlay) return;
    dom.modalOverlay.style.display = 'none';
    dom.modalBodyContent.innerHTML = '';
    toolState.activeModal = null;

    // Restore focus to previously active element
    if (previouslyActiveElement && typeof previouslyActiveElement.focus === 'function') {
      try {
        previouslyActiveElement.focus();
      } catch (err) {
        console.debug('Failed to restore focus:', err);
      }
      previouslyActiveElement = null;
    }
  }

  async function openGoogleWorkspaceModal(server) {
    toolState.activeModal = { type: 'google', serverId: server.id };
    openModal('SERVER CONFIG // GOOGLE WORKSPACE', async (body) => {
      body.innerHTML = '<div class="tools-loading" style="padding: 24px; text-align: center;">[ LOADING CONFIGURATION... ]</div>';

      let creds = {
        client_id: '',
        has_client_secret: false,
        is_configured: false,
        is_linked: false,
        account_email: null,
      };

      try {
        creds = await api.getGoogleCredentials();
      } catch (err) {
        console.warn('Failed to load Google credentials:', err);
      }

      const isConnected = creds.is_linked || (server.status === 'connected');
      const statusLabel = isConnected ? 'CONNECTED' : 'OFFLINE / NOT LINKED';
      const statusDotClass = isConnected ? 'connected' : 'offline';
      const email = creds.account_email || server.account_email || 'None';
      const safeEmail = escapeHtml(email);
      const safeClientId = escapeHtml(creds.client_id || '');
      const redirectUri = `${window.location.origin}/api/v1/tools/auth/google/callback`;

      body.innerHTML = `
        <div class="modal-status-box">
          <div class="modal-status-row">
            <span class="status-dot ${statusDotClass}"></span>
            <span style="font-weight: 700;">STATUS: ${statusLabel}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-secondary); margin-top: 4px;">
            LINKED ACCOUNT: <span style="color: var(--tars-cyan); font-weight: 600;">${safeEmail}</span>
          </div>
        </div>

        <div class="modal-action-block">
          <div class="modal-section-title">[ GOOGLE OAUTH2 ACCOUNT LINKING ]</div>
          <div class="modal-desc-box">
            ${isConnected 
              ? 'Google 계정이 정상적으로 연동되어 있습니다. TARS가 Calendar 일정 및 Gmail 메일을 관리할 수 있습니다.' 
              : 'Google 계정을 연동하여 TARS가 Calendar 일정 및 Gmail 메일을 관리할 수 있도록 승인합니다.'}
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
            <button id="btn-modal-google-oauth" class="hud-btn primary" style="flex: 1; justify-content: center; height: 38px; font-weight: 700;">
              🌐 ${isConnected ? 'RE-AUTHORIZE WITH GOOGLE' : 'AUTHORIZE VIA GOOGLE'}
            </button>
            ${isConnected ? `
            <button id="btn-modal-google-disconnect" class="hud-btn" style="height: 38px; font-weight: 700; border-color: var(--tars-red); color: var(--tars-red);">
              🚪 DISCONNECT ACCOUNT
            </button>
            ` : ''}
          </div>
        </div>

        <div class="modal-action-block">
          <div class="modal-section-title">[ OAUTH2 CLIENT CONFIGURATION ]</div>
          <div class="modal-desc-box" style="margin-bottom: 8px;">
            Google Cloud Console의 <b>OAuth 2.0 클라이언트 ID</b> 설정값을 등록합니다.
            <div style="margin-top: 6px; font-size: 10px; color: var(--text-muted); word-break: break-all;">
              승인된 리디렉션 URI: <code style="color: var(--tars-cyan); user-select: all;">${escapeHtml(redirectUri)}</code>
            </div>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px;">
            <div>
              <label style="font-size: 10px; color: var(--text-secondary); display: block; margin-bottom: 2px;">CLIENT ID</label>
              <input id="input-google-client-id" type="text" class="hud-input" placeholder="xxxx.apps.googleusercontent.com" value="${safeClientId}" style="width: 100%; box-sizing: border-box; font-family: monospace; font-size: 11px; padding: 6px 8px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); color: var(--text-primary);" />
            </div>
            <div>
              <label style="font-size: 10px; color: var(--text-secondary); display: block; margin-bottom: 2px;">
                CLIENT SECRET ${creds.has_client_secret ? '<span style="color: var(--tars-green); font-weight: 600;">(CONFIGURED)</span>' : '<span style="color: var(--tars-amber); font-weight: 600;">(NOT SET)</span>'}
              </label>
              <input id="input-google-client-secret" type="password" class="hud-input" placeholder="${creds.has_client_secret ? '•••••••••••••••• (Leave blank to keep existing)' : 'Enter Client Secret'}" style="width: 100%; box-sizing: border-box; font-family: monospace; font-size: 11px; padding: 6px 8px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); color: var(--text-primary);" />
            </div>
            <button id="btn-save-google-creds" class="hud-btn" style="justify-content: center; height: 34px; font-weight: 600; margin-top: 4px;">
              💾 SAVE CREDENTIALS
            </button>
          </div>
        </div>

        <div style="font-size: 11px; color: var(--text-muted);">
          AVAILABLE TOOLS:
          <ul style="padding-left: 18px; margin-top: 4px; line-height: 1.6;">
            <li>Google Calendar (calendar_list_events, calendar_create_event, calendar_delete_event)</li>
            <li>Google Gmail (gmail_search_messages, gmail_get_message, gmail_send_message)</li>
          </ul>
        </div>
      `;

      // Wire OAuth redirect button
      const oauthBtn = body.querySelector('#btn-modal-google-oauth');
      if (oauthBtn) {
        oauthBtn.addEventListener('click', async () => {
          oauthBtn.disabled = true;
          oauthBtn.textContent = 'CONNECTING TO GOOGLE AUTH...';
          try {
            const res = await api.getGoogleAuthUrl();
            if (res && res.url) {
              window.location.href = res.url;
            } else {
              throw new Error('No authorization URL returned from server.');
            }
          } catch (err) {
            showNotification(`OAuth Error: ${err.message}`, 'error');
            oauthBtn.disabled = false;
            oauthBtn.textContent = isConnected ? '🌐 RE-AUTHORIZE WITH GOOGLE' : '🌐 AUTHORIZE VIA GOOGLE';
          }
        });
      }

      // Wire Disconnect button
      const disconnectBtn = body.querySelector('#btn-modal-google-disconnect');
      if (disconnectBtn) {
        disconnectBtn.addEventListener('click', async () => {
          if (!confirm('정말로 Google Workspace 계정 연동을 해제하시겠습니까?')) return;
          disconnectBtn.disabled = true;
          disconnectBtn.textContent = 'DISCONNECTING...';
          try {
            const res = await api.disconnectGoogle();
            showNotification(res.message || 'Google account disconnected.', 'success');
            await loadToolServers();
            const updated = toolState.servers.find((s) => s.id === 'google_workspace');
            if (updated && toolState.activeModal && toolState.activeModal.type === 'google') {
              openGoogleWorkspaceModal(updated);
            }
          } catch (err) {
            showNotification(`Disconnect Error: ${err.message}`, 'error');
            disconnectBtn.disabled = false;
            disconnectBtn.textContent = '🚪 DISCONNECT ACCOUNT';
          }
        });
      }

      // Wire Save Credentials button
      const saveCredsBtn = body.querySelector('#btn-save-google-creds');
      if (saveCredsBtn) {
        saveCredsBtn.addEventListener('click', async () => {
          const clientIdInput = body.querySelector('#input-google-client-id');
          const clientSecretInput = body.querySelector('#input-google-client-secret');
          const clientId = clientIdInput ? clientIdInput.value.trim() : '';
          const clientSecret = clientSecretInput ? clientSecretInput.value.trim() : '';

          saveCredsBtn.disabled = true;
          saveCredsBtn.textContent = 'SAVING...';
          try {
            await api.updateGoogleCredentials(
              clientId,
              clientSecret || undefined
            );
            showNotification('Google OAuth credentials updated successfully.', 'success');
            await loadToolServers();
            const updated = toolState.servers.find((s) => s.id === 'google_workspace');
            if (updated && toolState.activeModal && toolState.activeModal.type === 'google') {
              openGoogleWorkspaceModal(updated);
            }
          } catch (err) {
            showNotification(`Save Error: ${err.message}`, 'error');
            saveCredsBtn.disabled = false;
            saveCredsBtn.textContent = '💾 SAVE CREDENTIALS';
          }
        });
      }
    });
  }

  function openMCPServerModal(server) {
    toolState.activeModal = { type: 'mcp', serverId: server.id };
    const safeServerName = escapeHtml(server.name || 'Server');
    openModal(`MCP SERVER CONFIG // ${safeServerName.toUpperCase()}`, (body) => {
      const isConnected = server.status === 'connected';
      const isMock = server.status === 'mock' || server.is_mock;
      const statusLabel = isMock ? 'MOCK MODE' : isConnected ? 'CONNECTED' : 'OFFLINE';
      const statusDotClass = isMock ? 'mock' : isConnected ? 'connected' : 'offline';
      const safeTransport = escapeHtml((server.transport || 'SSE').toUpperCase());
      const safeUrl = escapeHtml(server.url || 'N/A');

      body.innerHTML = `
        <div class="modal-status-box">
          <div class="modal-status-row">
            <span class="status-dot ${statusDotClass}"></span>
            <span style="font-weight: 700;">SERVER STATUS: ${statusLabel}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-secondary);">
            PROTOCOL: <span style="color: var(--tars-cyan); font-weight: 600;">${safeTransport}</span>
          </div>
        </div>

        <div class="form-group">
          <label style="font-size: 11px; color: var(--text-secondary); text-transform: uppercase;">ENDPOINT URL</label>
          <input type="text" class="hud-input" value="${safeUrl}" readonly style="font-family: var(--font-mono); font-size: 12px;">
        </div>

        <div class="form-group">
          <label style="font-size: 11px; color: var(--text-secondary); text-transform: uppercase;">CUSTOM REQUEST HEADERS (JSON)</label>
          <textarea class="hud-input" readonly rows="3" style="font-family: var(--font-mono); font-size: 11px; resize: none;">{\n  "User-Agent": "TARS-MCP-Client/2.4"\n}</textarea>
        </div>

        <div class="modal-action-block">
          <div class="modal-section-title">[ CONNECTION HEALTH & DIAGNOSTICS ]</div>
          <div id="mcp-test-result" style="font-size: 11.5px; color: var(--text-secondary);">
            Click below to execute a real-time connectivity ping to this MCP server.
          </div>
          <button id="btn-modal-test-mcp" class="hud-btn primary" style="justify-content: center; height: 38px; font-weight: 700;">
            ⚡ TEST CONNECTION
          </button>
        </div>
      `;

      const testBtn = body.querySelector('#btn-modal-test-mcp');
      const testResultBox = body.querySelector('#mcp-test-result');
      if (testBtn) {
        testBtn.addEventListener('click', async () => {
          testBtn.disabled = true;
          testBtn.textContent = 'RUNNING PING...';
          testResultBox.innerHTML = '<span style="color: var(--tars-cyan);">[ PINGING ENDPOINT... ]</span>';
          try {
            const res = await api.testServerConnection(server.id);
            const statusColor = res.status === 'offline' ? 'var(--tars-red)' : 'var(--tars-green)';
            const safeStatus = escapeHtml((res.status || '').toUpperCase());
            const safeLatency = escapeHtml(Number(res.latency_ms || 0).toFixed(1));
            const safeMessage = escapeHtml(res.message || '');
            testResultBox.innerHTML = `
              <div style="margin-top: 4px; line-height: 1.6;">
                Status: <span style="color: ${statusColor}; font-weight: 700;">${safeStatus}</span><br>
                Latency: <span style="color: var(--tars-cyan); font-weight: 700;">${safeLatency} ms</span><br>
                Message: <span>${safeMessage}</span>
              </div>
            `;
            showNotification(`MCP Test: ${safeStatus} (${safeLatency}ms)`, res.status === 'offline' ? 'error' : 'success');
            await loadToolServers();
          } catch (err) {
            const safeErr = escapeHtml(err.message || 'Connection error');
            testResultBox.innerHTML = `<span style="color: var(--tars-red);">[ TEST FAILED: ${safeErr} ]</span>`;
            showNotification(`MCP Test Error: ${err.message}`, 'error');
          } finally {
            testBtn.disabled = false;
            testBtn.textContent = '⚡ TEST CONNECTION';
          }
        });
      }
    });
  }

  function openToolInspectorModal(tool, server) {
    const safeToolName = escapeHtml(tool.name || 'unnamed');
    const safeServerName = escapeHtml(server.name || 'unknown');
    openModal(`TOOL // ${safeToolName}`, (body) => {
      let paramsRows = '';
      const properties = tool.parameters?.properties || {};
      const requiredList = tool.parameters?.required || [];

      for (const [paramName, paramInfo] of Object.entries(properties)) {
        const isReq = requiredList.includes(paramName);
        const safeParamName = escapeHtml(paramName);
        const safeType = escapeHtml(paramInfo?.type || 'any');
        const safeDesc = escapeHtml(paramInfo?.description || '-');
        paramsRows += `
          <tr>
            <td class="param-name">${safeParamName}</td>
            <td style="color: var(--text-secondary); font-family: var(--font-mono);">${safeType}</td>
            <td class="${isReq ? 'param-req' : ''}">${isReq ? 'YES' : 'NO'}</td>
            <td style="color: var(--text-secondary);">${safeDesc}</td>
          </tr>
        `;
      }

      if (!paramsRows) {
        paramsRows = `<tr><td colspan="4" style="color: var(--text-muted); text-align: center; padding: 12px;">No parameters required.</td></tr>`;
      }

      const safeToolDesc = escapeHtml(tool.description || 'No description provided.');

      body.innerHTML = `
        <div class="modal-status-box">
          <div style="font-size: 11px; color: var(--text-secondary);">
            SERVER: <span style="color: var(--tars-cyan); font-weight: 700;">${safeServerName}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-secondary);">
            STATUS: <span style="color: ${tool.active ? 'var(--tars-green)' : 'var(--text-muted)'}; font-weight: 700;">${tool.active ? 'ACTIVE' : 'DISABLED'}</span>
          </div>
        </div>

        <div>
          <div class="modal-section-title">FUNCTIONAL DESCRIPTION</div>
          <p style="margin-top: 6px; font-size: 12px; line-height: 1.6; color: var(--text-primary);">${safeToolDesc}</p>
        </div>

        <div>
          <div class="modal-section-title">PARAMETER SCHEMA</div>
          <div style="overflow-x: auto; margin-top: 6px; border: 1px solid var(--border-dim); border-radius: var(--radius-xs);">
            <table class="param-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Type</th>
                  <th>Required</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                ${paramsRows}
              </tbody>
            </table>
          </div>
        </div>
      `;
    });
  }

  // --- Tool & Server UI Helpers (G5) ---
  function updateServerActiveBadge(server, activeBadgeElem) {
    if (!activeBadgeElem) return;
    const activeCount = (server.tools || []).filter((t) => t.active).length;
    const totalCount = (server.tools || []).length;
    server.active_tools = activeCount;
    server.active_tools_count = activeCount;
    server.total_tools = totalCount;
    server.total_tools_count = totalCount;

    activeBadgeElem.textContent = `${activeCount}/${totalCount} ACTIVE`;
    activeBadgeElem.className = `active-badge ${
      activeCount === totalCount ? 'active' : activeCount > 0 ? 'partial' : 'disabled'
    }`;
  }

  function updateGlobalActiveBadge() {
    if (!dom.toolsGlobalBadge) return;
    let totalActive = 0;
    let totalTools = 0;
    toolState.servers.forEach((s) => {
      totalActive += (s.tools || []).filter((t) => t.active).length;
      totalTools += (s.tools || []).length;
    });
    dom.toolsGlobalBadge.textContent = `${totalActive}/${totalTools}`;
  }

  async function handleToolToggle(tool, server, checkbox, badgeElem, activeBadgeElem) {
    const toolName = tool.name;
    if (toolState.updatingTools.has(toolName)) return;

    toolState.updatingTools.add(toolName);
    const prevActive = !checkbox.checked;
    const newActive = checkbox.checked;

    // Optimistic UI updates
    badgeElem.textContent = newActive ? 'ACTIVE' : 'DISABLED';
    badgeElem.className = `tool-badge ${newActive ? 'active' : 'disabled'}`;
    checkbox.disabled = true;

    // Locally update state object
    tool.active = newActive;
    tool.enabled = newActive;

    // Recalculate badge counts in UI
    updateServerActiveBadge(server, activeBadgeElem);
    updateGlobalActiveBadge();

    try {
      const res = await api.toggleTool(toolName, newActive);
      // Ensure local state matches server response
      const confirmedActive = res.active ?? newActive;
      tool.active = confirmedActive;
      tool.enabled = confirmedActive;
      badgeElem.textContent = confirmedActive ? 'ACTIVE' : 'DISABLED';
      badgeElem.className = `tool-badge ${confirmedActive ? 'active' : 'disabled'}`;
      checkbox.checked = confirmedActive;
      updateServerActiveBadge(server, activeBadgeElem);
      updateGlobalActiveBadge();
    } catch (err) {
      // Rollback on error
      tool.active = prevActive;
      tool.enabled = prevActive;
      checkbox.checked = prevActive;
      badgeElem.textContent = prevActive ? 'ACTIVE' : 'DISABLED';
      badgeElem.className = `tool-badge ${prevActive ? 'active' : 'disabled'}`;
      updateServerActiveBadge(server, activeBadgeElem);
      updateGlobalActiveBadge();
      showNotification(`Failed to toggle ${toolName}: ${err.message}`, 'error');
    } finally {
      checkbox.disabled = false;
      toolState.updatingTools.delete(toolName);
    }
  }

  function renderToolsAccordion() {
    if (!dom.toolsServerList) return;
    dom.toolsServerList.innerHTML = '';

    if (!toolState.servers || toolState.servers.length === 0) {
      dom.toolsServerList.innerHTML = '<div class="tools-loading">[ NO SERVERS AVAILABLE ]</div>';
      updateGlobalActiveBadge();
      return;
    }

    toolState.servers.forEach((server) => {
      const isExpanded = toolState.expandedServerIds.has(server.id);
      const accordionItem = document.createElement('div');
      accordionItem.className = `server-accordion ${isExpanded ? 'expanded' : ''}`;
      accordionItem.setAttribute('data-server-id', server.id);

      const isConnected = server.status === 'connected';
      const isMock = server.status === 'mock' || server.is_mock;
      const statusDotClass = isMock ? 'mock' : isConnected ? 'connected' : 'offline';

      const activeCount = (server.tools || []).filter((t) => t.active).length;
      const totalCount = (server.tools || []).length;
      const badgeClass =
        activeCount === totalCount ? 'active' : activeCount > 0 ? 'partial' : 'disabled';
      const serverType = server.type === 'builtin' ? 'BUILTIN' : 'MCP';
      const safeServerName = escapeHtml(server.name || 'Server');
      const safeServerStatus = escapeHtml((server.status || 'unknown').toUpperCase());

      // Header
      const header = document.createElement('div');
      header.className = 'server-accordion-header';
      header.innerHTML = `
        <div class="server-header-left">
          <span class="accordion-chevron">▶</span>
          <span class="status-dot ${statusDotClass}" title="Status: ${safeServerStatus}"></span>
          <span class="server-title" title="${safeServerName}">${safeServerName}</span>
          <span class="server-type-badge ${escapeHtml(server.type || 'mcp')}">${serverType}</span>
        </div>
        <div class="server-header-right">
          <span class="active-badge ${badgeClass}">${activeCount}/${totalCount} ACTIVE</span>
          <button class="server-gear-btn" title="Configure server" aria-label="Configure ${safeServerName}">⚙️</button>
        </div>
      `;

      // Accordion Body
      const body = document.createElement('div');
      body.className = 'server-accordion-body';

      const activeBadgeElem = header.querySelector('.active-badge');
      const gearBtn = header.querySelector('.server-gear-btn');

      // Click on gear button opens config modal without collapsing or toggling accordion
      gearBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (server.id === 'google_workspace') {
          openGoogleWorkspaceModal(server);
        } else {
          openMCPServerModal(server);
        }
      });

      // Header click handling: consistently toggle accordion expansion for all servers
      header.addEventListener('click', () => {
        if (toolState.expandedServerIds.has(server.id)) {
          toolState.expandedServerIds.delete(server.id);
          accordionItem.classList.remove('expanded');
        } else {
          toolState.expandedServerIds.add(server.id);
          accordionItem.classList.add('expanded');
        }
      });

      // Render tool rows inside body
      (server.tools || []).forEach((tool) => {
        const row = document.createElement('div');
        row.className = 'tool-row';
        row.setAttribute('data-tool-name', tool.name);

        const safeToolName = escapeHtml(tool.name || 'tool');
        const rawDesc = tool.description || 'No description';
        const shortDesc = rawDesc.length > 40 ? rawDesc.substring(0, 40) + '...' : rawDesc;
        const safeShortDesc = escapeHtml(shortDesc);
        const safeFullDesc = escapeHtml(rawDesc);

        row.innerHTML = `
          <div class="tool-info-col">
            <div class="tool-name-wrap">
              <span class="tool-name" title="${safeToolName}">${safeToolName}</span>
              <button class="tool-info-btn" title="Inspect tool schema" aria-label="Inspect ${safeToolName}">ℹ</button>
            </div>
            <div class="tool-desc-short" title="${safeFullDesc}">${safeShortDesc}</div>
          </div>
          <div class="tool-action-col">
            <span class="tool-badge ${tool.active ? 'active' : 'disabled'}">${tool.active ? 'ACTIVE' : 'DISABLED'}</span>
            <label class="hud-switch" title="Toggle ${safeToolName}">
              <input type="checkbox" class="tool-toggle-checkbox" ${tool.active ? 'checked' : ''}>
              <span class="hud-switch-slider"></span>
            </label>
          </div>
        `;

        const infoBtn = row.querySelector('.tool-info-btn');
        const badgeElem = row.querySelector('.tool-badge');
        const toggleInput = row.querySelector('.tool-toggle-checkbox');

        infoBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          openToolInspectorModal(tool, server);
        });

        toggleInput.addEventListener('change', () => {
          handleToolToggle(tool, server, toggleInput, badgeElem, activeBadgeElem);
        });

        body.appendChild(row);
      });

      accordionItem.appendChild(header);
      accordionItem.appendChild(body);
      dom.toolsServerList.appendChild(accordionItem);
    });

    updateGlobalActiveBadge();
  }

  async function loadToolServers() {
    if (!dom.toolsServerList) return;
    try {
      const res = await api.getToolServers();
      toolState.servers = res.servers || [];
      renderToolsAccordion();
    } catch (err) {
      console.warn('[Tools] Failed to load tool servers:', err);
      dom.toolsServerList.innerHTML = `
        <div class="tools-loading" style="color: var(--tars-red);">
          [ FAILED TO LOAD TOOLS ]<br>
          <button id="btn-retry-tools" class="hud-btn" style="margin-top: 6px; font-size: 10px;">RETRY</button>
        </div>
      `;
      const retryBtn = dom.toolsServerList.querySelector('#btn-retry-tools');
      if (retryBtn) retryBtn.addEventListener('click', loadToolServers);
    }
  }

  function checkUrlAuthStatus() {
    const urlParams = new URLSearchParams(window.location.search);
    const authStatus = urlParams.get('auth_status');
    const authError = urlParams.get('error');

    if (authStatus === 'google_linked') {
      showNotification('Google Workspace account linked successfully.', 'success');
      const cleanUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, document.title, cleanUrl);
    } else if (authStatus === 'error' || authError) {
      const rawError = authError || 'Google authorization failed.';
      const safeError = escapeHtml(rawError);
      showNotification(`Google authorization error: ${safeError}`, 'error');
      const cleanUrl = window.location.pathname + window.location.hash;
      window.history.replaceState({}, document.title, cleanUrl);
    }
  }

  // --- App Initialization ---
  async function init() {
    registerServiceWorker();

    // Check URL parameters for OAuth2 redirect status (G5)
    checkUrlAuthStatus();

    // Setup Modal Dialog Event Listeners (G5)
    if (dom.modalCloseBtn) {
      dom.modalCloseBtn.addEventListener('click', closeModal);
    }
    if (dom.modalBtnCancel) {
      dom.modalBtnCancel.addEventListener('click', closeModal);
    }
    if (dom.modalOverlay) {
      dom.modalOverlay.addEventListener('click', (e) => {
        if (e.target === dom.modalOverlay) {
          closeModal();
        }
      });
    }
    window.addEventListener('keydown', (e) => {
      if (!dom.modalOverlay || dom.modalOverlay.style.display !== 'flex') return;

      if (e.key === 'Escape') {
        closeModal();
        return;
      }

      if (e.key === 'Tab' && dom.modalCard) {
        const focusableSelector =
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
        const focusables = Array.from(
          dom.modalCard.querySelectorAll(focusableSelector)
        ).filter((el) => el.offsetParent !== null);

        if (focusables.length === 0) return;

        const firstElem = focusables[0];
        const lastElem = focusables[focusables.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElem) {
            e.preventDefault();
            lastElem.focus();
          }
        } else {
          if (document.activeElement === lastElem) {
            e.preventDefault();
            firstElem.focus();
          }
        }
      }
    });

    // Setup Tools Refresh Button (G5)
    if (dom.btnRefreshTools) {
      dom.btnRefreshTools.addEventListener('click', () => {
        loadToolServers();
      });
    }

    // Setup TTS button state
    dom.btnTts.addEventListener('click', () => {
      const isMuted = tts.toggleMute();
      dom.btnTts.textContent = isMuted ? '🔇 TTS OFF' : '🔊 TTS ON';
      dom.btnTts.classList.toggle('active', !isMuted);
    });

    // Setup Sidebar Toggle (Mobile)
    dom.btnConfig.addEventListener('click', () => {
      dom.sidebar.classList.toggle('open');
    });

    // Setup Auth Tab Switching
    dom.tabLogin.addEventListener('click', () => switchAuthTab('login'));
    dom.tabSignup.addEventListener('click', () => switchAuthTab('signup'));

    // Login Form Submit
    dom.formLogin.addEventListener('submit', async (e) => {
      e.preventDefault();
      setAuthError('');
      const username = dom.loginUsername.value.trim();
      const password = dom.loginPassword.value;
      if (!username || !password) {
        setAuthError('Please fill in all fields.');
        return;
      }
      try {
        const res = await api.login(username, password);
        dom.userDisplayName.textContent = res.user?.username || username;
        showView('chat');
        await loadUserConfig();
        initStreamClient();
        await loadToolServers();
      } catch (err) {
        setAuthError(err.message || 'Login failed.');
      }
    });

    // Signup Form Submit
    dom.formSignup.addEventListener('submit', async (e) => {
      e.preventDefault();
      setAuthError('');
      const username = dom.signupUsername.value.trim();
      const email = dom.signupEmail.value.trim();
      const password = dom.signupPassword.value;
      if (!username || !email || !password) {
        setAuthError('Please fill in all fields.');
        return;
      }
      try {
        const res = await api.signup(username, email, password);
        dom.userDisplayName.textContent = res.user?.username || username;
        showView('chat');
        await loadUserConfig();
        initStreamClient();
        await loadToolServers();
      } catch (err) {
        setAuthError(err.message || 'Signup failed.');
      }
    });

    // Logout
    dom.btnLogout.addEventListener('click', () => {
      api.clearToken();
      if (streamClient) streamClient.disconnect();
      tts.stop();
      toolState.servers = [];
      if (dom.toolsServerList) {
        dom.toolsServerList.innerHTML = '<div class="tools-loading">[ DISCOVERING SERVERS & TOOLS... ]</div>';
      }
      updateGlobalActiveBadge();
      showView('auth');
    });

    // Unauthorized Event Handler
    window.addEventListener('tars:unauthorized', () => {
      toolState.servers = [];
      showView('auth');
      setAuthError('Session expired. Please log in again.');
    });

    // Persona Sliders
    dom.humorSlider.addEventListener('input', () => {
      dom.humorVal.textContent = `${dom.humorSlider.value}%`;
      scheduleConfigUpdate();
    });

    dom.honestySlider.addEventListener('input', () => {
      dom.honestyVal.textContent = `${dom.honestySlider.value}%`;
      scheduleConfigUpdate();
    });

    // Persona Mode Switch
    dom.modeCompanion.addEventListener('click', async () => {
      try {
        const updated = await api.updateConfig({ mode: 'companion' });
        applyConfigToUI(updated);
      } catch (err) {
        console.warn('[Config] Mode change error:', err);
      }
    });

    dom.modeWork.addEventListener('click', async () => {
      try {
        const updated = await api.updateConfig({ mode: 'work' });
        applyConfigToUI(updated);
      } catch (err) {
        console.warn('[Config] Mode change error:', err);
      }
    });

    // Reset Config Button
    dom.btnResetConfig.addEventListener('click', async () => {
      try {
        const reset = await api.resetConfig();
        applyConfigToUI(reset);
      } catch (err) {
        console.warn('[Config] Reset failed:', err);
      }
    });

    // Chat Input Auto-Grow & Keyboard Submit
    let isComposing = false;

    dom.chatInput.addEventListener('compositionstart', () => {
      isComposing = true;
    });

    dom.chatInput.addEventListener('compositionend', () => {
      // Safari/macOS IME edge case: delay clearing flag to avoid duplicate submission
      setTimeout(() => {
        isComposing = false;
      }, 20);
    });

    dom.chatInput.addEventListener('input', () => {
      dom.chatInput.style.height = 'auto';
      dom.chatInput.style.height = `${Math.min(dom.chatInput.scrollHeight, 120)}px`;
    });

    dom.chatInput.addEventListener('keydown', (e) => {
      if (e.isComposing || isComposing || e.keyCode === 229) {
        return;
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    });

    dom.sendBtn.addEventListener('click', () => {
      handleSendMessage();
    });

    // Check Initial Session
    const token = api.getToken();
    if (token) {
      try {
        const user = await api.getMe();
        dom.userDisplayName.textContent = user?.username || 'Cooper';
        showView('chat');
        await loadUserConfig();
        initStreamClient();
        await loadToolServers();
      } catch {
        api.clearToken();
        showView('auth');
      }
    } else {
      showView('auth');
    }
  }

  // Run on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
