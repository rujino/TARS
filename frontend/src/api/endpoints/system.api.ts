import { apiClient } from '../client';
import type { HealthCheckResponse, ReadinessResponse } from '@/types/system.types';

export const systemApi = {
  /**
   * 경량 라이브니스 프로브
   * GET /health
   */
  getHealth: async (): Promise<HealthCheckResponse> => {
    const { data } = await apiClient.get<HealthCheckResponse>('/health');
    return data;
  },

  /**
   * 라이브니스 프로브 상세
   * GET /health/liveness
   */
  getLiveness: async (): Promise<HealthCheckResponse> => {
    const { data } = await apiClient.get<HealthCheckResponse>('/health/liveness');
    return data;
  },

  /**
   * DB 및 스토리지 연결 점검을 포함한 심층 레디니스 프로브
   * GET /health/readiness
   */
  getReadiness: async (): Promise<ReadinessResponse> => {
    const { data } = await apiClient.get<ReadinessResponse>('/health/readiness');
    return data;
  },

  /**
   * Prometheus 텔레메트리 메트릭 텍스트
   * GET /metrics
   */
  getMetrics: async (): Promise<string> => {
    const { data } = await apiClient.get<string>('/metrics', {
      responseType: 'text',
      headers: {
        Accept: 'text/plain',
      },
    });
    return data;
  },
};
