import React, { useEffect, useRef } from 'react';
import styles from './ChatFeed.module.css';
import type { ChatMessageResponse } from '@/types/chat.types';

export interface StreamingMessageState {
  speaker: string;
  content: string;
  isStreaming: boolean;
  isAborted?: boolean;
}

interface ChatFeedProps {
  messages: ChatMessageResponse[];
  streamingMessage?: StreamingMessageState | null;
  readReceipts?: Record<string, { veraRead?: boolean; miuRead?: boolean; unreadCount?: number }>;
  userName?: string;
}

export const ChatFeed: React.FC<ChatFeedProps> = ({
  messages,
  streamingMessage,
  readReceipts = {},
  userName = '나',
}) => {
  const feedRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingMessage?.content]);

  return (
    <div className={styles.feedContainer} ref={feedRef}>
      {messages.map((msg) => {
        const isUser = msg.role === 'user';
        const speaker = (msg.speaker || (isUser ? 'user' : 'vera')).toLowerCase();
        const receipt = readReceipts[msg.id];

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
                {msg.content}
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

      {/* 실시간 스트리밍 버블 */}
      {streamingMessage && streamingMessage.content && (
        <div className={`${styles.messageRow} ${styles.messageRowAssistant}`}>
          <div
            className={`${styles.avatar} ${
              streamingMessage.speaker === 'miu' ? styles.avatarMiu : styles.avatarVera
            }`}
          >
            {streamingMessage.speaker === 'miu' ? '미우' : '베라'}
          </div>

          <div className={styles.bubbleWrapper}>
            <div
              className={`${styles.speakerName} ${
                streamingMessage.speaker === 'miu' ? styles.speakerMiu : styles.speakerVera
              }`}
            >
              <span>
                {streamingMessage.speaker === 'miu' ? '🐾 미우' : '🏛️ 베라'}
              </span>
            </div>

            <div
              className={`${styles.bubble} ${styles.bubbleAssistant} ${
                streamingMessage.isStreaming ? styles.bubbleStreaming : ''
              }`}
            >
              {streamingMessage.content}
              {streamingMessage.isStreaming && <span className={styles.cursor} />}
            </div>

            {streamingMessage.isAborted && (
              <div className={styles.abortedNotice}>
                <span>⛔ 0ms Barge-in (발화 중단됨)</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
