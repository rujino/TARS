import React, { useEffect, useRef, useState } from 'react';
import styles from './ChatPage.module.css';
import { useSessionStore } from '@/stores/useSessionStore';
import { useChatQuery } from '@/queries/useChatQuery';
import { useAuthQuery } from '@/queries/useAuthQuery';
import { useUIStore } from '@/stores/useUIStore';
import { tarsWsClient } from '@/websocket/client';
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
      (prevSessionId === null || prevSessionId === 'default_session') &&
      activeSessionId !== null &&
      activeSessionId !== 'default_session' &&
      (appendedMessages.length > 0 || streamingMessages.length > 0);

    if (!isNewSessionAssignment) {
      setAppendedMessages([]);
      setStreamingMessages([]);
    }
  }

  // Deduplicate: filter out optimistic user messages if the server messages already include them
  const pendingAppended = React.useMemo(() => {
    if (remoteMessages.length === 0) return appendedMessages;
    return appendedMessages.filter((appMsg) => {
      return !remoteMessages.some((rm) => {
        if (rm.role !== appMsg.role) return false;
        return rm.content.trim() === appMsg.content.trim();
      });
    });
  }, [remoteMessages, appendedMessages]);

  const allMessages = React.useMemo(() => {
    return [...remoteMessages, ...pendingAppended];
  }, [remoteMessages, pendingAppended]);

  // Clean up transient streaming & appended states when fresh remote messages arrive
  useEffect(() => {
    if (remoteMessages && remoteMessages.length > 0) {
      setStreamingMessages((prev) => {
        const hasActiveStreaming = prev.some((m) => m.isStreaming);
        return hasActiveStreaming ? prev : [];
      });
      setAppendedMessages((prev) => {
        return prev.filter((appMsg) => {
          return !remoteMessages.some((rm) => {
            if (rm.role !== appMsg.role) return false;
            return rm.content.trim() === appMsg.content.trim();
          });
        });
      });
    }
  }, [remoteMessages]);

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
        if (session_id && session_id !== 'default_session' && (!activeSessionIdRef.current || activeSessionIdRef.current === 'default_session')) {
          setActiveSession(session_id);
        }
        setStreamingMessages([]);
      },
      onStreamEnd: ({ session_id }) => {
        if (session_id && session_id !== 'default_session' && (!activeSessionIdRef.current || activeSessionIdRef.current === 'default_session')) {
          setActiveSession(session_id);
        }
        // Stop cursor animation on completed streaming bubbles
        setStreamingMessages((prev) =>
          prev.map((m) => ({ ...m, isStreaming: false }))
        );
        setTypingState(null);
        setAppendedMessages([]);
        refetchSessionsRef.current?.();
        void (async () => {
          try {
            const res = await refetchMessagesRef.current?.();
            if (res?.data && res.data.length > 0) {
              setStreamingMessages([]);
              setAppendedMessages([]);
            }
          } catch (e) {
            console.error('[Failed to refetch messages after stream]:', e);
          }
        })();
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

    // Reset previous streaming bubble state before starting a new turn
    setStreamingMessages([]);

    const messageId = `user-${Date.now()}`;
    const targetSessionId = activeSessionIdRef.current || undefined;
    const isNewSession = !activeSessionIdRef.current;

    // Optimistic user turn (단일 현재 전송 턴만 유지하여 이전 메시지 중복 노출 방지)
    const newMsg: ChatMessageResponse = {
      id: messageId,
      session_id: targetSessionId || '',
      user_id: user?.id || 'anonymous',
      role: 'user',
      content,
      tokens: content.length,
      created_at: new Date().toISOString(),
    };
    setAppendedMessages([newMsg]);

    try {
      tarsWsClient.sendChatMessage(content, targetSessionId, messageId, isNewSession);
    } catch (err) {
      alert('메시지 전송 실패: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  const handleBargeIn = () => {
    tarsWsClient.sendBargeIn(activeSessionIdRef.current || undefined);
  };

  const handleTyping = () => {
    tarsWsClient.sendTyping(activeSessionIdRef.current || undefined, 'active');
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

  return (
    <div className={styles.pageContainer}>
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
