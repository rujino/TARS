import React, { useEffect, useRef, useMemo } from 'react';
import styles from './ChatFeed.module.css';
import type { ChatMessageResponse } from '@/types/chat.types';
import { cleanSpeakerPrefix, splitMultiSpeakerMessage } from '@/utils/chat.utils';

export interface StreamingMessageState {
  speaker: string;
  content: string;
  isStreaming: boolean;
  isAborted?: boolean;
}

interface ChatFeedProps {
  messages: ChatMessageResponse[];
  streamingMessages?: StreamingMessageState[] | null;
  /** @deprecated Kept for backwards compatibility */
  streamingMessage?: StreamingMessageState | null;
  readReceipts?: Record<string, { veraRead?: boolean; miuRead?: boolean; unreadCount?: number }>;
  userName?: string;
}

export const ChatFeed: React.FC<ChatFeedProps> = ({
  messages,
  streamingMessages,
  streamingMessage,
  readReceipts = {},
  userName = '나',
}) => {
  const feedRef = useRef<HTMLDivElement>(null);

  const activeStreamingMessages: StreamingMessageState[] = useMemo(() => {
    if (streamingMessages && streamingMessages.length > 0) {
      return streamingMessages;
    }
    if (streamingMessage) {
      return [streamingMessage];
    }
    return [];
  }, [streamingMessages, streamingMessage]);

  // Split any multi-speaker combined messages (e.g. from server history)
  const processedMessages = useMemo(() => {
    const result: ChatMessageResponse[] = [];
    for (const msg of messages) {
      if (msg.role === 'assistant' && msg.content) {
        const splits = splitMultiSpeakerMessage(msg);
        result.push(...splits);
      } else {
        result.push(msg);
      }
    }
    return result;
  }, [messages]);

  const scrollToBottom = () => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [processedMessages, activeStreamingMessages]);

  return (
    <div className={styles.feedContainer} ref={feedRef}>
      {processedMessages.map((msg) => {
        const isUser = msg.role === 'user';
        const speaker = (msg.speaker || (isUser ? 'user' : 'vera')).toLowerCase();
        const receipt = readReceipts[msg.id];
        const displayContent = isUser ? msg.content : cleanSpeakerPrefix(msg.content, speaker);

        return (
          <div
            key={msg.id}
            className={`${styles.messageRow} ${
              isUser ? styles.messageRowUser : styles.messageRowAssistant
            }`}
          >
            <div
              className={`${styles.avatar} ${
                isUser
                  ? styles.avatarUser
                  : speaker === 'miu'
                  ? styles.avatarMiu
                  : styles.avatarVera
              }`}
            >
              {isUser ? userName.charAt(0).toUpperCase() : speaker === 'miu' ? '미우' : '베라'}
            </div>

            <div className={styles.bubbleWrapper}>
              <div
                className={`${styles.speakerName} ${
                  speaker === 'miu'
                    ? styles.speakerMiu
                    : speaker === 'vera'
                    ? styles.speakerVera
                    : ''
                }`}
              >
                <span>{isUser ? userName : speaker === 'miu' ? '🐾 미우' : '🏛️ 베라'}</span>
              </div>

              <div
                className={`${styles.bubble} ${
                  isUser ? styles.bubbleUser : styles.bubbleAssistant
                }`}
              >
                {displayContent}
              </div>

              {isUser && (
                <div className={styles.receiptRow}>
                  {receipt ? (
                    <>
                      {receipt.veraRead && (
                        <span className={`${styles.receiptTag} ${styles.receiptTagRead}`}>
                          베라 읽음
                        </span>
                      )}
                      {receipt.miuRead && (
                        <span className={`${styles.receiptTag} ${styles.receiptTagRead}`}>
                          미우 읽음
                        </span>
                      )}
                      {typeof receipt.unreadCount === 'number' && receipt.unreadCount > 0 && (
                        <span className={styles.receiptTag}>
                          안읽음 {receipt.unreadCount}
                        </span>
                      )}
                    </>
                  ) : (
                    <span className={styles.receiptTag}>전송됨</span>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* 실시간 스트리밍 버블들 (미우, 베라 등 다자간 동시/순차 발화 지원) */}
      {activeStreamingMessages.map((sm, index) => {
        if (!sm.content || !sm.content.trim()) return null;
        const speaker = (sm.speaker || 'vera').toLowerCase();
        const displayContent = cleanSpeakerPrefix(sm.content, speaker);
        if (!displayContent && !sm.isStreaming) return null;

        return (
          <div
            key={`streaming-${speaker}-${index}`}
            className={`${styles.messageRow} ${styles.messageRowAssistant}`}
          >
            <div
              className={`${styles.avatar} ${
                speaker === 'miu' ? styles.avatarMiu : styles.avatarVera
              }`}
            >
              {speaker === 'miu' ? '미우' : '베라'}
            </div>

            <div className={styles.bubbleWrapper}>
              <div
                className={`${styles.speakerName} ${
                  speaker === 'miu' ? styles.speakerMiu : styles.speakerVera
                }`}
              >
                <span>{speaker === 'miu' ? '🐾 미우' : '🏛️ 베라'}</span>
              </div>

              <div
                className={`${styles.bubble} ${styles.bubbleAssistant} ${
                  sm.isStreaming
                    ? speaker === 'miu'
                      ? styles.bubbleStreamingMiu
                      : styles.bubbleStreamingVera
                    : ''
                }`}
              >
                {displayContent}
                {sm.isStreaming && (
                  <span
                    className={`${styles.cursor} ${
                      speaker === 'miu' ? styles.cursorMiu : styles.cursorVera
                    }`}
                  />
                )}
              </div>

              {sm.isAborted && (
                <div className={styles.abortedNotice}>
                  <span>⛔ 0ms Barge-in (발화 중단됨)</span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
