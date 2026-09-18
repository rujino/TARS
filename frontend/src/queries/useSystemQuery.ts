import { useQuery } from '@tanstack/react-query';
import { systemApi } from '@/api/endpoints/system.api';
import { queryKeys } from './queryKeys';

export const useSystemQuery = () => {
  const healthQuery = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: () => systemApi.getHealth(),
    refetchInterval: 30 * 1000,
    retry: 1,
  });

  const livenessQuery = useQuery({
    queryKey: queryKeys.system.liveness(),
    queryFn: () => systemApi.getLiveness(),
    refetchInterval: 30 * 1000,
    retry: 1,
  });

  const readinessQuery = useQuery({
    queryKey: queryKeys.system.readiness(),
    queryFn: () => systemApi.getReadiness(),
    refetchInterval: 15 * 1000,
    retry: 1,
  });

  const metricsQuery = useQuery({
    queryKey: queryKeys.system.metrics(),
    queryFn: () => systemApi.getMetrics(),
    enabled: false, // On-demand fetch when system modal opens
  });

  return {
    health: healthQuery.data,
    isHealthy: healthQuery.data?.status === 'ok',
    isLoadingHealth: healthQuery.isLoading,
    refetchHealth: healthQuery.refetch,

    liveness: livenessQuery.data,
    isLoadingLiveness: livenessQuery.isLoading,
    refetchLiveness: livenessQuery.refetch,

    readiness: readinessQuery.data,
    isReady: readinessQuery.data?.status === 'ready',
    isLoadingReadiness: readinessQuery.isLoading,
    refetchReadiness: readinessQuery.refetch,

    metrics: metricsQuery.data,
    isLoadingMetrics: metricsQuery.isLoading,
    refetchMetrics: metricsQuery.refetch,
  };
};
