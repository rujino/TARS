import React, { useMemo, useRef, useEffect } from 'react';
import styles from './ChatFeed.module.css';
import type { ChatMessageResponse } from '@/types/chat.types';
import { cleanSpeakerPrefix, splitMultiSpeakerMessage } from '@/utils/chat.utils';
import { ChatBubble } from './ChatBubble';
import { ToolExecutionBubble, type ToolExecutionState } from './ToolExecutionBubble';

export interface StreamingMessageState {
  speaker: string;
  content: string;
  isStreaming: boolean;
  isAborted?: boolean;
}

interface ChatFeedProps {
  messages: ChatMessageResponse[];
  streamingMessages?: StreamingMessageState[] | null;
  toolExecutions?: ToolExecutionState[];
  readReceipts?: Record<string, { veraRead?: boolean; miuRead?: boolean; unreadCount?: number }>;
  userName?: string;
}

export const ChatFeed: React.FC<ChatFeedProps> = ({
  messages,
  streamingMessages = [],
  toolExecutions = [],
  readReceipts = {},
  userName = '나',
}) => {
  const feedRef = useRef<HTMLDivElement>(null);

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

  const activeStreaming = useMemo(() => {
    return (streamingMessages || []).filter(
      (sm) => Boolean(sm.content && sm.content.trim()) || sm.isStreaming
    );
  }, [streamingMessages]);

  // column-reverse 컨테이너는 scrollTop = 0이 최신 메시지(바닥) 위치
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
  }, [processedMessages.length, activeStreaming.length, toolExecutions.length]);

  const isEmpty =
    processedMessages.length === 0 &&
    activeStreaming.length === 0 &&
    toolExecutions.length === 0;

  return (
    <div className={styles.feedContainer} ref={feedRef}>
      {/* 
        column-reverse에서는 DOM의 앞쪽에 위치한 요소가 시각적으로 맨 아래(화면 50% 가슴 높이)에 맺힙니다.
        따라서:
        1. 최신 스트리밍 버블
        2. 최신 도구 실행 버블
        3. 과거 메시지들 (최신순 역정렬)
        순으로 배치합니다.
      */}

      {/* 1. 실시간 스트리밍 버블들 (최신) */}
      {activeStreaming.map((sm, index) => {
        const rawSpeaker = (sm.speaker || 'vera').toLowerCase();
        const speaker: 'vera' | 'miu' = rawSpeaker === 'miu' ? 'miu' : 'vera';
        const displayContent = cleanSpeakerPrefix(sm.content, speaker);

        return (
          <ChatBubble
            key={`streaming-${speaker}-${index}`}
            speaker={speaker}
            content={displayContent}
            isStreaming={sm.isStreaming}
            isAborted={sm.isAborted}
          />
        );
      })}

      {/* 2. 도구 실행 버블들 */}
      {toolExecutions.map((toolExec, index) => (
        <ToolExecutionBubble
          key={`tool-${toolExec.callId || index}`}
          execution={toolExec}
        />
      ))}

      {/* 3. 누적 대화 메시지들 (최신이 먼저 오도록 reverse) */}
      {[...processedMessages].reverse().map((msg) => {
        const isUser = msg.role === 'user';
        const rawSpeaker = (msg.speaker || (isUser ? 'user' : 'vera')).toLowerCase();
        const speaker: 'vera' | 'miu' | 'user' = isUser
          ? 'user'
          : rawSpeaker === 'miu'
          ? 'miu'
          : 'vera';
        const receipt = readReceipts[msg.id];
        const displayContent = isUser ? msg.content : cleanSpeakerPrefix(msg.content, speaker);

        return (
          <ChatBubble
            key={msg.id}
            speaker={speaker}
            content={displayContent}
            readReceipt={receipt}
            userName={userName}
          />
        );
      })}

      {/* 4. 최상단 스크롤 여유 공간 (column-reverse의 DOM 끝 = 시각적 최상단) */}
      {!isEmpty && <div style={{ height: 36, minHeight: 36, flexShrink: 0 }} aria-hidden="true" />}

      {/* 5. 초기 대화 없을 때의 안내 카드 */}
      {isEmpty && (
        <div className={styles.emptyState}>
          <div className={styles.emptyIcon}>✨</div>
          <div className={styles.emptyTitle}>TARS 메이드 룸에 오신 것을 환영합니다</div>
          <div className={styles.emptyDesc}>
            베라와 미우가 주인님의 말씀을 경청하고 있습니다.
            <br />
            아래 입력창에 메시지를 남겨보세요.
          </div>
        </div>
      )}
    </div>
  );
};
