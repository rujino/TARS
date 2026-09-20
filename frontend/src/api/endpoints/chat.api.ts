import { apiClient } from '../client';
import type {
  ChatMessageResponse,
  ChatSessionDeleteResponse,
  ChatSessionListResponse,
  GreetingResponse,
} from '@/types/chat.types';

export const chatApi = {
  /**
   * 앱 시작 시 상황 인지형 인트로 인사 생성
   * GET /api/v1/chat/greeting
   */
  getGreeting: async (timezone: string = 'Asia/Seoul'): Promise<GreetingResponse> => {
    const { data } = await apiClient.get<GreetingResponse>('/api/v1/chat/greeting', {
      params: { timezone },
    });
    return data;
  },

  /**
   * 세션 목록 조회 (날짜 그룹 메타데이터 포함)
   * GET /api/v1/chat/sessions
   */
  getSessions: async (params?: {
    limit?: number;
    offset?: number;
    timezone?: string;
  }): Promise<ChatSessionListResponse> => {
    const { data } = await apiClient.get<ChatSessionListResponse>('/api/v1/chat/sessions', {
      params: {
        limit: params?.limit ?? 50,
        offset: params?.offset ?? 0,
        timezone: params?.timezone ?? 'Asia/Seoul',
      },
    });
    return data;
  },

  /**
   * 특정 세션의 전체 메시지 턴 복원
   * GET /api/v1/chat/sessions/{session_id}/messages
   */
  getSessionMessages: async (sessionId: string): Promise<ChatMessageResponse[]> => {
    const { data } = await apiClient.get<ChatMessageResponse[]>(
      `/api/v1/chat/sessions/${sessionId}/messages`
    );
    return data;
  },

  /**
   * 세션 삭제 (메시지 cascade 삭제)
   * DELETE /api/v1/chat/sessions/{session_id}
   */
  deleteSession: async (sessionId: string): Promise<ChatSessionDeleteResponse> => {
    const { data } = await apiClient.delete<ChatSessionDeleteResponse>(
      `/api/v1/chat/sessions/${sessionId}`
    );
    return data;
  },

  /**
   * 모든 세션 및 대화 내역 일괄 삭제 (DB 정리/초기화)
   * DELETE /api/v1/chat/sessions/all
   */
  deleteAllSessions: async (): Promise<ChatSessionDeleteResponse> => {
    const { data } = await apiClient.delete<ChatSessionDeleteResponse>(
      '/api/v1/chat/sessions/all'
    );
    return data;
  },

  /**
   * WebSocket 접속 엔드포인트 URL 반환
   * WS /api/v1/chat/ws
   */
  getWsUrl: (ticket?: string): string => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const base = `${protocol}//${host}/api/v1/chat/ws`;
    return ticket ? `${base}?ticket=${encodeURIComponent(ticket)}` : base;
  },
};
