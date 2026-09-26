import React from 'react';
import styles from './ChatBubble.module.css';

interface ChatBubbleProps {
  speaker: 'vera' | 'miu' | 'user';
  content: string;
  isStreaming?: boolean;
  isAborted?: boolean;
  readReceipt?: { veraRead?: boolean; miuRead?: boolean; unreadCount?: number };
  userName?: string;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({
  speaker,
  content,
  isStreaming = false,
  isAborted = false,
  readReceipt,
  userName = '나',
}) => {
  const isVera = speaker === 'vera';
  const isMiu = speaker === 'miu';
  const isUser = speaker === 'user';

  const rowClass = isVera
    ? styles.rowVera
    : isMiu
    ? styles.rowMiu
    : styles.rowUser;

  const cardClass = isVera
    ? styles.cardVera
    : isMiu
    ? styles.cardMiu
    : styles.cardUser;

  const headerClass = isVera
    ? styles.speakerVera
    : isMiu
    ? styles.speakerMiu
    : styles.speakerUser;

  const displayName = isUser
    ? `👤 ${userName}`
    : isVera
    ? '🏛️ 베라'
    : '🐾 미우';

  return (
    <div className={`${styles.bubbleWrapper} ${rowClass}`}>
      <div className={`${styles.speakerHeader} ${headerClass}`}>
        <span>{displayName}</span>
      </div>

      <div className={`${styles.bubbleCard} ${cardClass}`}>
        {content}
        {isStreaming && (
          <span
            className={`${styles.cursor} ${
              isVera ? styles.cursorVera : isMiu ? styles.cursorMiu : ''
            }`}
          />
        )}
      </div>

      {isAborted && (
        <div className={styles.abortedNotice}>
          <span>⛔ 0ms Barge-in (발화 중단됨)</span>
        </div>
      )}

      {isUser && readReceipt && (
        <div className={styles.metaRow}>
          {readReceipt.veraRead && (
            <span className={`${styles.receiptBadge} ${styles.receiptRead}`}>
              베라 읽음
            </span>
          )}
          {readReceipt.miuRead && (
            <span className={`${styles.receiptBadge} ${styles.receiptRead}`}>
              미우 읽음
            </span>
          )}
          {typeof readReceipt.unreadCount === 'number' && readReceipt.unreadCount > 0 && (
            <span className={styles.receiptBadge}>
              안읽음 {readReceipt.unreadCount}
            </span>
          )}
        </div>
      )}
    </div>
  );
};
