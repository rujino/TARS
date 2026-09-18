import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { personaApi } from '@/api/endpoints/persona.api';
import { queryKeys } from './queryKeys';
import type { TARSConfigUpdateRequest } from '@/types/persona.types';

export const usePersonaQuery = () => {
  const queryClient = useQueryClient();
  const token = typeof window !== 'undefined' ? localStorage.getItem('tars_token') : null;

  const configQuery = useQuery({
    queryKey: queryKeys.persona.config(),
    queryFn: () => personaApi.getConfig(),
    enabled: !!token,
    staleTime: 30 * 1000,
  });

  const updateConfigMutation = useMutation({
    mutationFn: (payload: TARSConfigUpdateRequest) => personaApi.updateConfig(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.persona.config(), data);
    },
  });

  const resetConfigMutation = useMutation({
    mutationFn: () => personaApi.resetConfig(),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.persona.config(), data);
    },
  });

  return {
    config: configQuery.data,
    isLoadingConfig: configQuery.isLoading,
    refetchConfig: configQuery.refetch,
    updateConfig: updateConfigMutation.mutateAsync,
    isUpdatingConfig: updateConfigMutation.isPending,
    resetConfig: resetConfigMutation.mutateAsync,
    isResettingConfig: resetConfigMutation.isPending,
  };
};
