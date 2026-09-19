import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from '@/api/endpoints/auth.api';
import { queryKeys } from './queryKeys';
import type { UserLoginRequest, UserSignupRequest } from '@/types/auth.types';

export const useAuthQuery = () => {
  const queryClient = useQueryClient();

  const token = typeof window !== 'undefined' ? localStorage.getItem('tars_token') : null;

  const meQuery = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: () => authApi.getMe(),
    enabled: !!token,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const loginMutation = useMutation({
    mutationFn: (payload: UserLoginRequest) => authApi.login(payload),
    onSuccess: (data) => {
      localStorage.setItem('tars_token', data.access_token);
      queryClient.setQueryData(queryKeys.auth.me(), data.user);
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.persona.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.all });
    },
  });

  const signupMutation = useMutation({
    mutationFn: (payload: UserSignupRequest) => authApi.signup(payload),
    onSuccess: (data) => {
      localStorage.setItem('tars_token', data.access_token);
      queryClient.setQueryData(queryKeys.auth.me(), data.user);
      queryClient.invalidateQueries({ queryKey: queryKeys.chat.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.persona.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tools.all });
    },
  });

  const issueWsTicketMutation = useMutation({
    mutationFn: () => authApi.issueWsTicket(),
  });

  const logout = () => {
    localStorage.removeItem('tars_token');
    queryClient.removeQueries({ queryKey: queryKeys.auth.all });
    queryClient.removeQueries({ queryKey: queryKeys.chat.all });
    queryClient.removeQueries({ queryKey: queryKeys.persona.all });
    queryClient.removeQueries({ queryKey: queryKeys.tools.all });
    window.location.reload();
  };

  return {
    user: meQuery.data,
    isLoadingUser: meQuery.isLoading,
    isLoggedIn: !!token && !meQuery.isError,
    login: loginMutation.mutateAsync,
    isLoggingIn: loginMutation.isPending,
    loginError: loginMutation.error,
    signup: signupMutation.mutateAsync,
    isSigningUp: signupMutation.isPending,
    signupError: signupMutation.error,
    issueWsTicket: issueWsTicketMutation.mutateAsync,
    logout,
    refetchMe: meQuery.refetch,
  };
};
