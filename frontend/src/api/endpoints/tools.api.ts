import { apiClient } from '../client';
import type {
  GoogleAuthCallbackResponse,
  GoogleAuthUrlResponse,
  GoogleCredentialsRequest,
  GoogleCredentialsResponse,
  ServerTestResponse,
  ToolsServersResponse,
  ToolToggleRequest,
  ToolToggleResponse,
} from '@/types/tools.types';

export const toolsApi = {
  /**
   * 등록된 도구 서버 및 도구 목록 조회
   * GET /api/v1/tools/servers
   */
  getServers: async (): Promise<ToolsServersResponse> => {
    const { data } = await apiClient.get<ToolsServersResponse>('/api/v1/tools/servers');
    return data;
  },

  /**
   * 특정 도구 활성/비활성화 상태 토글
   * PATCH /api/v1/tools/{tool_name}/toggle
   */
  toggleTool: async (toolName: string, payload?: ToolToggleRequest): Promise<ToolToggleResponse> => {
    const { data } = await apiClient.patch<ToolToggleResponse>(
      `/api/v1/tools/${toolName}/toggle`,
      payload ?? {}
    );
    return data;
  },

  /**
   * Google OAuth2 인증 URL 발급
   * GET /api/v1/tools/auth/google/url
   */
  getGoogleAuthUrl: async (redirectUri?: string): Promise<GoogleAuthUrlResponse> => {
    const { data } = await apiClient.get<GoogleAuthUrlResponse>(
      '/api/v1/tools/auth/google/url',
      {
        params: redirectUri ? { redirect_uri: redirectUri } : undefined,
      }
    );
    return data;
  },

  /**
   * Google OAuth2 콜백 처리
   * GET /api/v1/tools/auth/google/callback
   */
  handleGoogleCallback: async (params: {
    code: string;
    state?: string;
    error?: string;
    format?: string;
    redirect_uri?: string;
  }): Promise<GoogleAuthCallbackResponse> => {
    const { data } = await apiClient.get<GoogleAuthCallbackResponse>(
      '/api/v1/tools/auth/google/callback',
      {
        params: {
          ...params,
          format: 'json',
        },
      }
    );
    return data;
  },

  /**
   * Google OAuth2 클라이언트 설정 및 연동 상태 조회
   * GET /api/v1/tools/auth/google/credentials
   */
  getGoogleCredentials: async (): Promise<GoogleCredentialsResponse> => {
    const { data } = await apiClient.get<GoogleCredentialsResponse>(
      '/api/v1/tools/auth/google/credentials'
    );
    return data;
  },

  /**
   * 커스텀 Google OAuth2 Client ID/Secret 설정
   * POST /api/v1/tools/auth/google/credentials
   */
  updateGoogleCredentials: async (
    payload: GoogleCredentialsRequest
  ): Promise<GoogleCredentialsResponse> => {
    const { data } = await apiClient.post<GoogleCredentialsResponse>(
      '/api/v1/tools/auth/google/credentials',
      payload
    );
    return data;
  },

  /**
   * Google 워크스페이스 연동 해제 및 토큰 폐기
   * POST /api/v1/tools/auth/google/disconnect
   */
  disconnectGoogle: async (): Promise<{ message: string; success: boolean }> => {
    const { data } = await apiClient.post<{ message: string; success: boolean }>(
      '/api/v1/tools/auth/google/disconnect'
    );
    return data;
  },

  /**
   * MCP 서버 연결 테스트 및 지연시간 측정
   * POST /api/v1/tools/servers/{server_id}/test
   */
  testServer: async (serverId: string): Promise<ServerTestResponse> => {
    const { data } = await apiClient.post<ServerTestResponse>(
      `/api/v1/tools/servers/${serverId}/test`
    );
    return data;
  },
};
