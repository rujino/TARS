import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toolsApi } from '@/api/endpoints/tools.api';
import { queryKeys } from './queryKeys';
import type { GoogleCredentialsRequest, ToolToggleRequest } from '@/types/tools.types';

export const useToolsQuery = () => {
  const queryClient = useQueryClient();
  const token = typeof window !== 'undefined' ? localStorage.getItem('tars_token') : null;

  const serversQuery = useQuery({
    queryKey: queryKeys.tools.servers(),
    queryFn: () => toolsApi.getServers(),
    enabled: !!token,
    staleTime: 30 * 1000,
  });

  const googleCredentialsQuery = useQuery({
    queryKey: queryKeys.tools.googleCredentials(),
    queryFn: () => toolsApi.getGoogleCredentials(),
    enabled: !!token,
    staleTime: 30 * 1000,
  });

  const toggleToolMutation = useMutation({
    mutationFn: ({ toolName, payload }: { toolName: string; payload?: ToolToggleRequest }) =>
      toolsApi.toggleTool(toolName, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.servers() });
    },
  });

  const testServerMutation = useMutation({
    mutationFn: (serverId: string) => toolsApi.testServer(serverId),
  });

  const updateGoogleCredentialsMutation = useMutation({
    mutationFn: (payload: GoogleCredentialsRequest) => toolsApi.updateGoogleCredentials(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.tools.googleCredentials(), data);
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.servers() });
    },
  });

  const disconnectGoogleMutation = useMutation({
    mutationFn: () => toolsApi.disconnectGoogle(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.googleCredentials() });
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.servers() });
    },
  });

  return {
    servers: serversQuery.data?.servers ?? [],
    isLoadingServers: serversQuery.isLoading,
    refetchServers: serversQuery.refetch,

    googleCredentials: googleCredentialsQuery.data,
    isLoadingGoogleCredentials: googleCredentialsQuery.isLoading,
    refetchGoogleCredentials: googleCredentialsQuery.refetch,

    toggleTool: toggleToolMutation.mutateAsync,
    isTogglingTool: toggleToolMutation.isPending,

    testServer: testServerMutation.mutateAsync,
    isTestingServer: testServerMutation.isPending,

    updateGoogleCredentials: updateGoogleCredentialsMutation.mutateAsync,
    isUpdatingGoogleCredentials: updateGoogleCredentialsMutation.isPending,

    disconnectGoogle: disconnectGoogleMutation.mutateAsync,
    isDisconnectingGoogle: disconnectGoogleMutation.isPending,

    getGoogleAuthUrl: toolsApi.getGoogleAuthUrl,
    handleGoogleCallback: toolsApi.handleGoogleCallback,
  };
};
