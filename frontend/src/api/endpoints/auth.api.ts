import { apiClient } from '../client';
import type {
  TokenResponse,
  UserLoginRequest,
  UserResponse,
  UserSignupRequest,
  WebSocketTicketResponse,
} from '@/types/auth.types';

export const authApi = {
  /**
   * 신규 사용자 회원가입
   * POST /api/v1/auth/signup
   */
  signup: async (payload: UserSignupRequest): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/api/v1/auth/signup', payload);
    return data;
  },

  /**
   * 사용자 로그인 및 JWT 발급
   * POST /api/v1/auth/login
   */
  login: async (payload: UserLoginRequest): Promise<TokenResponse> => {
    const { data } = await apiClient.post<TokenResponse>('/api/v1/auth/login', payload);
    return data;
  },

  /**
   * 현재 인증된 사용자 프로필 조회
   * GET /api/v1/auth/me
   */
  getMe: async (): Promise<UserResponse> => {
    const { data } = await apiClient.get<UserResponse>('/api/v1/auth/me');
    return data;
  },

  /**
   * WebSocket 연결용 1회용 단기 티켓 발급
   * POST /api/v1/auth/ws-ticket
   */
  issueWsTicket: async (): Promise<WebSocketTicketResponse> => {
    const { data } = await apiClient.post<WebSocketTicketResponse>('/api/v1/auth/ws-ticket');
    return data;
  },
};
