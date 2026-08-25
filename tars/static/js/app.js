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
            `<div style="color: var(--tars-red); margin-top: 8px; font-size: 12px;">[ERROR: ${errorMsg}]</div>`;
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

  // --- App Initialization ---
  async function init() {
    registerServiceWorker();

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
      } catch (err) {
        setAuthError(err.message || 'Signup failed.');
      }
    });

    // Logout
    dom.btnLogout.addEventListener('click', () => {
      api.clearToken();
      if (streamClient) streamClient.disconnect();
      tts.stop();
      showView('auth');
    });

    // Unauthorized Event Handler
    window.addEventListener('tars:unauthorized', () => {
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
    dom.chatInput.addEventListener('input', () => {
      dom.chatInput.style.height = 'auto';
      dom.chatInput.style.height = `${Math.min(dom.chatInput.scrollHeight, 120)}px`;
    });

    dom.chatInput.addEventListener('keydown', (e) => {
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
