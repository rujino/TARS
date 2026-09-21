import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { chatApi } from '@/api/endpoints/chat.api';
import { queryKeys } from './queryKeys';

export const useChatQuery = (activeSessionId?: string | null) => {
  const queryClient = useQueryClient();
  const token = typeof window !== 'undefined' ? localStorage.getItem('tars_token') : null;

  const sessionsQuery = useQuery({
    queryKey: queryKeys.chat.sessions(),
    queryFn: () => chatApi.getSessions(),
    enabled: !!token,
    staleTime: 10 * 1000,
  });

  // Guard: placeholder session IDs (e.g. 'default_session') are not real DB entities
  const PLACEHOLDER_SESSION_IDS = new Set(['default_session', 'ws_session', 'ws_default_session']);
  const isValidSessionId = !!activeSessionId && !PLACEHOLDER_SESSION_IDS.has(activeSessionId);

  const messagesQuery = useQuery({
    queryKey: isValidSessionId ? queryKeys.chat.messages(activeSessionId) : ['chat', 'messages', 'none'],
    queryFn: () => (isValidSessionId ? chatApi.getSessionMessages(activeSessionId) : Promise.resolve([])),
    enabled: !!token && isValidSessionId,
    staleTime: 30 * 1000,
  });

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedSessionId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
      queryClient.removeQueries({ queryKey: queryKeys.chat.messages(deletedSessionId) });
    },
  });

  const deleteAllSessionsMutation = useMutation({
    mutationFn: () => chatApi.deleteAllSessions(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
      queryClient.removeQueries({ queryKey: ['chat', 'messages'] });
    },
  });

  return {
    // Sessions
    sessions: sessionsQuery.data?.sessions ?? [],
    sessionGroups: sessionsQuery.data?.groups ?? {},
    isLoadingSessions: sessionsQuery.isLoading,
    refetchSessions: sessionsQuery.refetch,

    // Messages
    messages: messagesQuery.data ?? [],
    isLoadingMessages: messagesQuery.isLoading,
    refetchMessages: messagesQuery.refetch,

    // Delete
    deleteSession: deleteSessionMutation.mutateAsync,
    isDeletingSession: deleteSessionMutation.isPending,
    deleteAllSessions: deleteAllSessionsMutation.mutateAsync,
    isDeletingAllSessions: deleteAllSessionsMutation.isPending,
  };
};
