export interface GreetingResponse {
  greeting: string;
  session_id: string;
  mode: string;
  idle_seconds: number;
}

export type DateGroupName = 'Today' | 'Yesterday' | 'Past 7 days' | 'Past 30 days' | 'Older';

export interface ChatSessionItem {
  id: string;
  user_id: string;
  title: string;
  status: string;
  bridge_summary?: string | null;
  parent_session_id?: string | null;
  last_active_at: string;
  created_at: string;
  updated_at: string;
  date_group: DateGroupName | string;
  message_count: number;
}

export interface ChatSessionListResponse {
  sessions: ChatSessionItem[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  groups: Record<string, ChatSessionItem[]>;
}

export interface ChatMessageResponse {
  id: string;
  session_id: string;
  user_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tokens: number;
  created_at: string;
  speaker?: 'vera' | 'miu' | 'master' | string;
  read_by?: string[];
  unread_count?: number;
}

export interface ChatSessionDeleteResponse {
  success: boolean;
  session_id: string;
  message: string;
}

export interface WSMessageIn {
  type: 'chat_message' | 'user_barge_in' | 'user_typing';
  session_id?: string;
  content?: string;
  timezone?: string;
  message_id?: string;
  status?: 'active' | 'inactive';
}

export interface WSMessageOut {
  type:
    | 'stream_start'
    | 'token'
    | 'stream_end'
    | 'error'
    | 'read_receipt'
    | 'typing_indicator'
    | 'typing_ack'
    | 'stream_abort';
  session_id?: string;
  content?: string;
  delta?: string;
  title?: string;
  error?: string;
  message_id?: string;
  reader?: 'vera' | 'miu' | string;
  unread_count?: number;
  sender?: 'vera' | 'miu' | string;
  status?: 'active' | 'inactive';
  label?: string;
  speaker?: 'vera' | 'miu' | string;
  avatar?: string;
  turn_epoch?: number;
  turn_state?: string;
  reason?: string;
}
