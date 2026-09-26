import { authApi } from '@/api/endpoints/auth.api';
import { chatApi } from '@/api/endpoints/chat.api';
import type { WSEventHandlers, WSConnectionStatus } from './types';
import type { WSMessageOut } from '@/types/chat.types';

export class TarsWebSocketClient {
  private ws: WebSocket | null = null;
  private status: WSConnectionStatus = 'disconnected';
  private handlers: Set<WSEventHandlers> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimer: number | null = null;
  private isExplicitlyClosed = false;

  public getStatus(): WSConnectionStatus {
    return this.status;
  }

  public subscribe(handler: WSEventHandlers): () => void {
    this.handlers.add(handler);
    handler.onStatusChange?.(this.status);
    return () => {
      this.handlers.delete(handler);
    };
  }

  private setStatus(newStatus: WSConnectionStatus) {
    this.status = newStatus;
    this.handlers.forEach((h) => h.onStatusChange?.(newStatus));
  }

  public async connect(): Promise<void> {
    const token = localStorage.getItem('tars_token');
    if (!token) {
      this.setStatus('disconnected');
      return;
    }

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isExplicitlyClosed = false;
    this.setStatus(this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting');

    try {
      // 1. Issue short-lived ticket
      const { ticket } = await authApi.issueWsTicket();
      const wsUrl = chatApi.getWsUrl(ticket);

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setStatus('connected');
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WSMessageOut;
          this.handleIncomingMessage(data);
        } catch (err) {
          console.error('[WS Parse Error]:', err);
        }
      };

      this.ws.onerror = (err) => {
        console.warn('[WS Error]:', err);
      };

      this.ws.onclose = (event) => {
        this.ws = null;
        if (event.code === 4001) {
          // Auth failed / ticket expired / user inactive
          this.setStatus('disconnected');
          return;
        }

        if (!this.isExplicitlyClosed) {
          this.setStatus('disconnected');
          this.scheduleReconnect();
        } else {
          this.setStatus('disconnected');
        }
      };
    } catch (err) {
      console.warn('[WS Connect Ticket Error]:', err);
      this.setStatus('disconnected');
      if (!this.isExplicitlyClosed) {
        this.scheduleReconnect();
      }
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.setStatus('disconnected');
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
    this.reconnectAttempts++;
    this.reconnectTimer = window.setTimeout(() => {
      this.connect();
    }, delay);
  }

  public disconnect() {
    this.isExplicitlyClosed = true;
    if (this.reconnectTimer) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('disconnected');
  }

  private handleIncomingMessage(msg: WSMessageOut) {
    this.handlers.forEach((h) => {
      switch (msg.type) {
        case 'token':
          if (msg.delta || msg.content) {
            h.onToken?.({
              speaker: msg.speaker || 'vera',
              token: msg.delta || msg.content || '',
              turn_epoch: msg.turn_epoch,
            });
          }
          break;
        case 'stream_start':
          h.onStreamStart?.({ session_id: msg.session_id, turn_epoch: msg.turn_epoch });
          break;
        case 'stream_end':
          h.onStreamEnd?.({ session_id: msg.session_id, turn_epoch: msg.turn_epoch });
          break;
        case 'stream_abort':
          h.onStreamAbort?.({
            reason: msg.reason,
            session_id: msg.session_id,
            turn_epoch: msg.turn_epoch,
          });
          break;
        case 'typing_indicator':
          h.onTypingIndicator?.({
            sender: msg.sender || 'miu',
            status: (msg.status as 'active' | 'inactive') || 'active',
            label: msg.label,
          });
          break;
        case 'read_receipt':
          h.onReadReceipt?.({
            reader: msg.reader || 'vera',
            message_id: msg.message_id,
            unread_count: msg.unread_count,
          });
          break;
        case 'tool_start':
          h.onToolStart?.({
            tool: msg.tool || '',
            call_id: msg.call_id,
            args: msg.args,
            speaker: msg.speaker || 'vera',
          });
          break;
        case 'tool_result':
          h.onToolResult?.({
            tool: msg.tool || '',
            call_id: msg.call_id,
            status: msg.status || 'success',
            result: msg.result,
            error: msg.error,
            speaker: msg.speaker || 'vera',
          });
          break;
        case 'error':
          h.onError?.(msg.error || msg.content || '서버 통신 오류가 발생했습니다.');
          break;
      }
    });
  }

  public sendChatMessage(
    content: string,
    sessionId?: string,
    messageId?: string,
    isNewSession?: boolean
  ) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket이 연결되어 있지 않습니다.');
    }
    this.ws.send(
      JSON.stringify({
        type: 'chat_message',
        content,
        session_id: sessionId || undefined,
        message_id: messageId,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Seoul',
        is_new_session: Boolean(isNewSession),
      })
    );
  }

  public sendBargeIn(sessionId?: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(
      JSON.stringify({
        type: 'user_barge_in',
        session_id: sessionId || undefined,
      })
    );
  }

  public sendTyping(sessionId?: string, status: 'active' | 'inactive' = 'active') {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(
      JSON.stringify({
        type: 'user_typing',
        session_id: sessionId || undefined,
        status,
      })
    );
  }
}

// 싱글톤 인스턴스
export const tarsWsClient = new TarsWebSocketClient();
