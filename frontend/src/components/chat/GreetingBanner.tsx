import React from 'react';
import styles from './GreetingBanner.module.css';
import type { GreetingResponse } from '@/types/chat.types';

interface GreetingBannerProps {
  greeting?: GreetingResponse | null;
  isLoading?: boolean;
}

export const GreetingBanner: React.FC<GreetingBannerProps> = ({ greeting, isLoading }) => {
  if (isLoading) {
    return (
      <div className={styles.banner}>
        <div className={styles.iconWrapper}>✨</div>
        <div className={styles.content}>
          <div className={styles.headerRow}>
            <span className={styles.title}>TARS 페르소나 인사 생성 중...</span>
          </div>
        </div>
      </div>
    );
  }

  if (!greeting) return null;

  const formatIdle = (seconds: number) => {
    if (seconds <= 0) return '새 세션 시작';
    if (seconds < 60) return `${seconds}초 전 활동`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}분 전 활동`;
    const hours = Math.floor(mins / 60);
    return `${hours}시간 전 활동`;
  };

  return (
    <div className={styles.banner}>
      <div className={styles.iconWrapper}>👋</div>
      <div className={styles.content}>
        <div className={styles.headerRow}>
          <span className={styles.title}>TARS Companion</span>
          <span className={styles.modeBadge}>{greeting.mode.toUpperCase()}</span>
        </div>
        <div className={styles.greetingText}>{greeting.greeting}</div>
        <div className={styles.metaRow}>
          <span>{formatIdle(greeting.idle_seconds)}</span>
        </div>
      </div>
    </div>
  );
};
