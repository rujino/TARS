import React, { useEffect, useState } from 'react';
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

  // Optimistic & local turns appended during active session
  const [appendedMessages, setAppendedMessages] = useState<ChatMessageResponse[]>([]);
  const [prevSessionId, setPrevSessionId] = useState(activeSessionId);
  const [streamingState, setStreamingState] = useState<StreamingMessageState | null>(null);
  const [typingState, setTypingState] = useState<{ sender: string; label?: string } | null>(null);
  const [readReceipts, setReadReceipts] = useState<
    Record<string, { veraRead?: boolean; miuRead?: boolean; unreadCount?: number }>
  >({});

  // Reset appended messages during render when session changes
  if (prevSessionId !== activeSessionId) {
    setPrevSessionId(activeSessionId);
    setAppendedMessages([]);
    setStreamingState(null);
  }

  const allMessages = [...remoteMessages, ...appendedMessages];

  // WebSocket lifecycle & event subscriptions
  useEffect(() => {
    if (!isLoggedIn) return;

    tarsWsClient.connect();

    const unsubscribe = tarsWsClient.subscribe({
      onToken: ({ speaker, token }) => {
        setStreamingState((prev) => {
          if (!prev) {
            return {
              speaker,
              content: token,
              isStreaming: true,
              isAborted: false,
            };
          }
          return {
            ...prev,
            speaker: speaker || prev.speaker,
            content: prev.content + token,
            isStreaming: true,
          };
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
        if (session_id && !activeSessionId) {
          setActiveSession(session_id);
        }
        setStreamingState({
          speaker: 'vera',
          content: '',
          isStreaming: true,
          isAborted: false,
        });
      },
      onStreamEnd: ({ session_id }) => {
        setStreamingState((current) => {
          if (current && current.content) {
            const newAssistantMsg: ChatMessageResponse = {
              id: `msg-${Date.now()}`,
              session_id: session_id || activeSessionId || 'default_session',
              user_id: user?.id || 'anonymous',
              role: 'assistant',
              speaker: current.speaker,
              content: current.content,
              tokens: current.content.length,
              created_at: new Date().toISOString(),
            };
            setAppendedMessages((prev) => [...prev, newAssistantMsg]);
          }
          return null;
        });
        setTypingState(null);
        refetchSessions();
        refetchMessages();
      },
      onStreamAbort: ({ reason }) => {
        setStreamingState((prev) =>
          prev ? { ...prev, isStreaming: false, isAborted: true } : null
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
  }, [isLoggedIn, activeSessionId, user?.id, setActiveSession, refetchSessions, refetchMessages]);

  const handleSendMessage = (content: string) => {
    if (!isLoggedIn) {
      openModal('auth');
      return;
    }

    const messageId = `user-${Date.now()}`;
    const targetSessionId = activeSessionId || 'default_session';

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
    tarsWsClient.sendBargeIn(activeSessionId || 'default_session');
  };

  const handleTyping = () => {
    tarsWsClient.sendTyping(activeSessionId || 'default_session', 'active');
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

  const showGreeting = !activeSessionId || allMessages.length === 0;

  return (
    <div className={styles.pageContainer}>
      {showGreeting && (
        <div className={styles.bannerWrapper}>
          <GreetingBanner greeting={greeting} isLoading={isLoadingGreeting} />
        </div>
      )}

      <ChatFeed
        messages={allMessages}
        streamingMessage={streamingState}
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
        isStreaming={!!streamingState?.isStreaming}
      />
    </div>
  );
};
