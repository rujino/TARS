import React from 'react';
import styles from './TypingIndicator.module.css';

interface TypingIndicatorProps {
  sender?: string;
  label?: string;
}

export const TypingIndicator: React.FC<TypingIndicatorProps> = ({
  sender = 'miu',
  label = '🐾 미우가 발을 동동 구르며 타자 치는 중...',
}) => {
  return (
    <div className={styles.container}>
      <div className={styles.avatar}>
        {sender.charAt(0).toUpperCase()}
      </div>
      <span className={styles.label}>{label}</span>
      <div className={styles.dots}>
        <div className={styles.dot} />
        <div className={styles.dot} />
        <div className={styles.dot} />
      </div>
    </div>
  );
};
