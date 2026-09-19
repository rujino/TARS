import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { chatApi } from '@/api/endpoints/chat.api';
import { queryKeys } from './queryKeys';

export const useChatQuery = (activeSessionId?: string | null) => {
  const queryClient = useQueryClient();
  const token = typeof window !== 'undefined' ? localStorage.getItem('tars_token') : null;

  const greetingQuery = useQuery({
    queryKey: queryKeys.chat.greeting(),
    queryFn: () => chatApi.getGreeting(),
    enabled: !!token,
    staleTime: 60 * 1000,
    retry: 1,
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.chat.sessions(),
    queryFn: () => chatApi.getSessions(),
    enabled: !!token,
    staleTime: 10 * 1000,
  });

  const messagesQuery = useQuery({
    queryKey: activeSessionId ? queryKeys.chat.messages(activeSessionId) : ['chat', 'messages', 'none'],
    queryFn: () => (activeSessionId ? chatApi.getSessionMessages(activeSessionId) : Promise.resolve([])),
    enabled: !!token && !!activeSessionId,
    staleTime: 30 * 1000,
  });

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => chatApi.deleteSession(sessionId),
    onSuccess: (_, deletedSessionId) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
      queryClient.removeQueries({ queryKey: queryKeys.chat.messages(deletedSessionId) });
    },
  });

  return {
    // Greeting
    greeting: greetingQuery.data,
    isLoadingGreeting: greetingQuery.isLoading,
    refetchGreeting: greetingQuery.refetch,

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
  };
};
