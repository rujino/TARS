import React, { useEffect, useRef, useState } from 'react';
import styles from './ChatPage.module.css';
import { useSessionStore } from '@/stores/useSessionStore';
import { useChatQuery } from '@/queries/useChatQuery';
import { useAuthQuery } from '@/queries/useAuthQuery';
import { useUIStore } from '@/stores/useUIStore';
import { tarsWsClient } from '@/websocket/client';
import { GreetingBanner } from '@/components/chat/GreetingBanner';
import { ChatFeed, type StreamingMessageState } from '@/components/chat/ChatFeed';
import { TypingIndicator } from '@/components/chat/TypingIndicator';
import { ChatInput } from '@/components/chat/ChatInput';
import type { ChatMessageResponse } from '@/types/chat.types';

export const ChatPage: React.FC = () => {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const setActiveSession = useSessionStore((state) => state.setActiveSession);
  const openModal = useUIStore((state) => state.openModal);

  const { user, isLoggedIn } = useAuthQuery();
  const {
    greeting,
    isLoadingGreeting,
    messages: remoteMessages,
    refetchSessions,
    refetchMessages,
  } = useChatQuery(activeSessionId);

  // Stable references for WebSocket event handlers
  const activeSessionIdRef = useRef(activeSessionId);
  const refetchMessagesRef = useRef(refetchMessages);
  const refetchSessionsRef = useRef(refetchSessions);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    refetchMessagesRef.current = refetchMessages;
    refetchSessionsRef.current = refetchSessions;
  }, [refetchMessages, refetchSessions]);

  // Optimistic & local turns appended during active session
  const [appendedMessages, setAppendedMessages] = useState<ChatMessageResponse[]>([]);
  const [prevSessionId, setPrevSessionId] = useState(activeSessionId);
  const [streamingMessages, setStreamingMessages] = useState<StreamingMessageState[]>([]);
  const [typingState, setTypingState] = useState<{ sender: string; label?: string } | null>(null);
  const [readReceipts, setReadReceipts] = useState<
    Record<string, { veraRead?: boolean; miuRead?: boolean; unreadCount?: number }>
  >({});

  // Reset appended messages when switching sessions,
  // but preserve optimistic turns and streaming state when transitioning from null -> new session_id for the ongoing turn.
  if (prevSessionId !== activeSessionId) {
    setPrevSessionId(activeSessionId);
    const isNewSessionAssignment =
      prevSessionId === null &&
      activeSessionId !== null &&
      (appendedMessages.length > 0 || streamingMessages.length > 0);

    if (!isNewSessionAssignment) {
      setAppendedMessages([]);
      setStreamingMessages([]);
    }
  }

  // Deduplicate: filter out optimistic messages if the server messages already include them
  const pendingAppended =
    remoteMessages.length > 0
      ? appendedMessages.filter(
          (appMsg) =>
            !remoteMessages.some(
              (rm) => rm.role === appMsg.role && rm.content === appMsg.content
            )
        )
      : appendedMessages;

  const allMessages = [...remoteMessages, ...pendingAppended];

  // WebSocket lifecycle & event subscriptions
  useEffect(() => {
    if (!isLoggedIn) return;

    tarsWsClient.connect();

    const unsubscribe = tarsWsClient.subscribe({
      onToken: ({ speaker, token }) => {
        const normalizedSpeaker = (speaker || 'vera').toLowerCase();
        setStreamingMessages((prev) => {
          const existingIndex = prev.findIndex(
            (m) => m.speaker.toLowerCase() === normalizedSpeaker
          );
          if (existingIndex >= 0) {
            const updated = [...prev];
            updated[existingIndex] = {
              ...updated[existingIndex],
              content: updated[existingIndex].content + token,
              isStreaming: true,
            };
            return updated;
          } else {
            return [
              ...prev,
              {
                speaker: normalizedSpeaker,
                content: token,
                isStreaming: true,
                isAborted: false,
              },
            ];
          }
        });
      },
      onTypingIndicator: ({ sender, status, label }) => {
        if (status === 'active') {
          setTypingState({ sender, label });
        } else {
          setTypingState(null);
        }
      },
      onReadReceipt: ({ reader, message_id, unread_count }) => {
        if (!message_id) return;
        setReadReceipts((prev) => {
          const current = prev[message_id] || {};
          return {
            ...prev,
            [message_id]: {
              ...current,
              veraRead: reader === 'vera' ? true : current.veraRead,
              miuRead: reader === 'miu' ? true : current.miuRead,
              unreadCount: typeof unread_count === 'number' ? unread_count : current.unreadCount,
            },
          };
        });
      },
      onStreamStart: ({ session_id }) => {
        if (session_id && !activeSessionIdRef.current) {
          setActiveSession(session_id);
        }
        setStreamingMessages([]);
      },
      onStreamEnd: async ({ session_id }) => {
        const targetSid = session_id || activeSessionIdRef.current || 'default_session';
        setStreamingMessages((currentList) => {
          if (currentList && currentList.length > 0) {
            const completedTurns: ChatMessageResponse[] = currentList
              .filter((m) => m.content && m.content.trim().length > 0)
              .map((m, index) => ({
                id: `msg-${Date.now()}-${index}`,
                session_id: targetSid,
                user_id: user?.id || 'anonymous',
                role: 'assistant',
                speaker: m.speaker,
                content: m.content,
                tokens: m.content.length,
                created_at: new Date(Date.now() + index * 50).toISOString(),
              }));

            if (completedTurns.length > 0) {
              setAppendedMessages((prev) => [...prev, ...completedTurns]);
            }
          }
          return [];
        });
        setTypingState(null);
        refetchSessionsRef.current?.();
        try {
          const res = await refetchMessagesRef.current?.();
          if (res?.data && res.data.length > 0) {
            setAppendedMessages([]);
          }
        } catch (e) {
          console.error('[Failed to refetch messages after stream]:', e);
        }
      },
      onStreamAbort: ({ reason }) => {
        setStreamingMessages((prev) =>
          prev.map((m) => ({ ...m, isStreaming: false, isAborted: true }))
        );
        setTypingState(null);
        console.info('[Stream Aborted]:', reason);
      },
      onError: (err) => {
        console.error('[WS Error Event]:', err);
      },
    });

    return () => {
      unsubscribe();
    };
  }, [isLoggedIn, user?.id, setActiveSession]);

  const handleSendMessage = (content: string) => {
    if (!isLoggedIn) {
      openModal('auth');
      return;
    }

    // Flush any ongoing streaming messages into appendedMessages before starting new turn
    if (streamingMessages.length > 0) {
      const pendingTurns: ChatMessageResponse[] = streamingMessages
        .filter((m) => m.content && m.content.trim().length > 0)
        .map((m, index) => ({
          id: `msg-flushed-${Date.now()}-${index}`,
          session_id: activeSessionIdRef.current || 'default_session',
          user_id: user?.id || 'anonymous',
          role: 'assistant',
          speaker: m.speaker,
          content: m.content,
          tokens: m.content.length,
          created_at: new Date(Date.now() + index * 50).toISOString(),
        }));
      if (pendingTurns.length > 0) {
        setAppendedMessages((prev) => [...prev, ...pendingTurns]);
      }
      setStreamingMessages([]);
    }

    const messageId = `user-${Date.now()}`;
    const targetSessionId = activeSessionIdRef.current || 'default_session';

    // Optimistic user turn
    const newMsg: ChatMessageResponse = {
      id: messageId,
      session_id: targetSessionId,
      user_id: user?.id || 'anonymous',
      role: 'user',
      content,
      tokens: content.length,
      created_at: new Date().toISOString(),
    };
    setAppendedMessages((prev) => [...prev, newMsg]);

    try {
      tarsWsClient.sendChatMessage(content, targetSessionId, messageId);
    } catch (err) {
      alert('메시지 전송 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleBargeIn = () => {
    tarsWsClient.sendBargeIn(activeSessionIdRef.current || 'default_session');
  };

  const handleTyping = () => {
    tarsWsClient.sendTyping(activeSessionIdRef.current || 'default_session', 'active');
  };

  if (!isLoggedIn) {
    return (
      <div className={styles.pageContainer}>
        <div className={styles.unauthWarning}>
          <div style={{ fontSize: '2.5rem' }}>🔐</div>
          <h2 className={styles.unauthTitle}>로그인이 필요합니다</h2>
          <p className={styles.unauthDesc}>
            TARS 페르소나(베라 & 미우)와의 실시간 다자간 대화, 도구 실행 및 세션 복원을 위해 먼저 로그인해주세요.
          </p>
          <button className={styles.unauthBtn} onClick={() => openModal('auth')}>
            로그인 또는 회원가입
          </button>
        </div>
      </div>
    );
  }

  const isCurrentlyStreaming = streamingMessages.some((m) => m.isStreaming);
  const showGreeting = allMessages.length === 0 && streamingMessages.length === 0;

  return (
    <div className={styles.pageContainer}>
      {showGreeting && (
        <div className={styles.bannerWrapper}>
          <GreetingBanner greeting={greeting} isLoading={isLoadingGreeting} />
        </div>
      )}

      <ChatFeed
        messages={allMessages}
        streamingMessages={streamingMessages}
        readReceipts={readReceipts}
        userName={user?.username || '나'}
      />

      <div className={styles.typingWrapper}>
        {typingState && (
          <TypingIndicator
            sender={typingState.sender}
            label={typingState.label}
          />
        )}
      </div>

      <ChatInput
        onSendMessage={handleSendMessage}
        onBargeIn={handleBargeIn}
        onTyping={handleTyping}
        isStreaming={isCurrentlyStreaming}
      />
    </div>
  );
};
