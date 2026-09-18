import { apiClient } from '../client';
import type {
  TARSConfigResponse,
  TARSConfigUpdateRequest,
} from '@/types/persona.types';

export const personaApi = {
  /**
   * TARS 현재 설정(운영 모드) 조회
   * GET /api/v1/tars/config
   */
  getConfig: async (): Promise<TARSConfigResponse> => {
    const { data } = await apiClient.get<TARSConfigResponse>('/api/v1/tars/config');
    return data;
  },

  /**
   * TARS 설정 부분 변경 (운영 모드: attend vs task)
   * PATCH /api/v1/tars/config
   */
  updateConfig: async (payload: TARSConfigUpdateRequest): Promise<TARSConfigResponse> => {
    const { data } = await apiClient.patch<TARSConfigResponse>('/api/v1/tars/config', payload);
    return data;
  },

  /**
   * TARS 설정 기본값 초기화
   * POST /api/v1/tars/config/reset
   */
  resetConfig: async (): Promise<TARSConfigResponse> => {
    const { data } = await apiClient.post<TARSConfigResponse>('/api/v1/tars/config/reset');
    return data;
  },
};
