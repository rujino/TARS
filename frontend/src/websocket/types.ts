export type WSConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

export interface WSEventHandlers {
  onToken?: (data: { speaker: string; token: string; turn_epoch?: number }) => void;
  onTypingIndicator?: (data: { sender: string; status: 'active' | 'inactive'; label?: string }) => void;
  onReadReceipt?: (data: { reader: string; message_id?: string; unread_count?: number }) => void;
  onStreamStart?: (data: { session_id?: string; turn_epoch?: number }) => void;
  onStreamEnd?: (data: { session_id?: string; turn_epoch?: number }) => void;
  onStreamAbort?: (data: { reason?: string; session_id?: string; turn_epoch?: number }) => void;
  onError?: (error: string) => void;
  onStatusChange?: (status: WSConnectionStatus) => void;
}
