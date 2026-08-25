/**
 * TARS Dual Streaming Client Module (WebSocket Primary + SSE Fallback)
 * Features:
 * - Real-time token streaming with lifecycle callbacks
 * - Exponential backoff reconnection for WebSocket
 * - Graceful fallback to Server-Sent Events (POST /api/v1/chat/stream)
 * - Automatic 401 Unauthorized detection
 */
class TARSStreamClient {
  constructor(apiClient, callbacks = {}) {
    this.api = apiClient;
    this.callbacks = callbacks; // onStart, onToken, onEnd, onError, onStatusChange
    this.ws = null;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 3;
    this.isFallbackSSE = false;
    this.currentSessionId = 'default_session';
  }

  connectWebSocket() {
    const token = this.api.getToken();
    if (!token) {
      this.callbacks.onStatusChange?.('OFFLINE');
      return;
    }

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/v1/chat/ws?token=${encodeURIComponent(token)}`;

    this.callbacks.onStatusChange?.('CONNECTING');

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.isFallbackSSE = false;
        this.callbacks.onStatusChange?.('ONLINE');
      };

      this.ws.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data);
          if (frame.type === 'stream_start') {
            this.callbacks.onStart?.(frame.session_id);
          } else if (frame.type === 'token') {
            this.callbacks.onToken?.(frame.content || frame.delta || '');
          } else if (frame.type === 'stream_end') {
            this.callbacks.onEnd?.(frame.content || '');
          } else if (frame.type === 'error') {
            this.callbacks.onError?.(frame.message || 'Stream error occurred');
          }
        } catch (err) {
          console.error('[Stream] WS JSON Parse Error:', err);
        }
      };

      this.ws.onclose = (event) => {
        if (event.code === 4001) {
          console.warn('[Stream] WS Auth failed (4001). Clearing token.');
          this.api.clearToken();
          window.dispatchEvent(new CustomEvent('tars:unauthorized'));
          this.callbacks.onStatusChange?.('OFFLINE');
          return;
        }
        this.handleDisconnect();
      };

      this.ws.onerror = () => {
        this.handleDisconnect();
      };
    } catch (err) {
      console.warn('[Stream] WS Connection failed, falling back:', err);
      this.handleDisconnect();
    }
  }

  disconnect() {
    if (this.ws) {
      try {
        this.ws.close();
      } catch (err) {
        console.warn('[Stream] Disconnect error:', err);
      }
      this.ws = null;
    }
    this.reconnectAttempts = 0;
  }

  handleDisconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.pow(2, this.reconnectAttempts) * 1000;
      this.callbacks.onStatusChange?.(`RECONNECTING (${this.reconnectAttempts})`);
      setTimeout(() => {
        if (this.api.getToken()) {
          this.connectWebSocket();
        }
      }, delay);
    } else {
      this.isFallbackSSE = true;
      this.callbacks.onStatusChange?.('SSE_FALLBACK');
    }
  }

  async sendMessage(message, sessionId = null) {
    const targetSession = sessionId || this.currentSessionId || 'default_session';
    this.currentSessionId = targetSession;

    if (!this.isFallbackSSE && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: 'chat_message',
          session_id: targetSession,
          content: message
        })
      );
    } else {
      // Fallback: SSE POST Stream
      await this.sendSSEMessage(message, targetSession);
    }
  }

  async sendSSEMessage(message, sessionId) {
    this.callbacks.onStart?.(sessionId);
    try {
      const token = this.api.getToken();
      const res = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ message, session_id: sessionId })
      });

      if (res.status === 401) {
        this.api.clearToken();
        window.dispatchEvent(new CustomEvent('tars:unauthorized'));
        throw new Error('Unauthorized');
      }

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      if (!res.body) {
        throw new Error('ReadableStream not supported by browser');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          if (!block.trim()) continue;
          let eventType = 'message';
          let dataStr = '';

          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) eventType = line.slice(6).trim();
            if (line.startsWith('data:')) dataStr = line.slice(5).trim();
          }

          if (eventType === 'token') {
            try {
              const dataObj = JSON.parse(dataStr);
              this.callbacks.onToken?.(dataObj.content || dataObj.delta || '');
            } catch {
              this.callbacks.onToken?.(dataStr);
            }
          } else if (eventType === 'stream_end') {
            try {
              const dataObj = JSON.parse(dataStr);
              this.callbacks.onEnd?.(dataObj.content || '');
            } catch {
              this.callbacks.onEnd?.(dataStr);
            }
          } else if (eventType === 'error') {
            try {
              const dataObj = JSON.parse(dataStr);
              this.callbacks.onError?.(dataObj.error || dataObj.message || 'SSE Error');
            } catch {
              this.callbacks.onError?.(dataStr);
            }
          }
        }
      }
    } catch (err) {
      console.error('[Stream] SSE Stream failed:', err);
      this.callbacks.onError?.(err.message || 'Stream connection failed');
    }
  }
}

if (typeof window !== 'undefined') {
  window.TARSStreamClient = TARSStreamClient;
}
