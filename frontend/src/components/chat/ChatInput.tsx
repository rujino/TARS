import React, { useRef, useState } from 'react';
import styles from './ChatInput.module.css';

interface ChatInputProps {
  onSendMessage: (content: string) => void;
  onBargeIn: () => void;
  onTyping: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  onBargeIn,
  onTyping,
  isStreaming,
  disabled = false,
}) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);

  const handleCompositionStart = () => {
    isComposingRef.current = true;
  };

  const handleCompositionEnd = () => {
    isComposingRef.current = false;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // macOS 및 한글 IME 조합(Composition) 중 발생한 Enter 키 이벤트는 건너뜁니다.
    // Chrome(Mac)에서는 자소 결합 완료 시 Enter 이벤트가 2회(조합 중 1회, 완료 후 1회) 발생하여
    // 첫 번째 이벤트에서 전송 처리할 경우 마지막 글자('녕')가 다시 입력창에 삽입되어 중복 전송됩니다.
    if (e.nativeEvent.isComposing || isComposingRef.current || e.key === 'Process') {
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    } else {
      onTyping();
    }
  };

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSendMessage(trimmed);
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    // Auto-adjust height
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`;
  };

  return (
    <div className={styles.inputContainer}>
      <div className={styles.inputWrapper}>
        <textarea
          ref={textareaRef}
          className={styles.textarea}
          rows={1}
          placeholder="TARS에게 메시지를 입력하세요... (Enter: 전송, Shift+Enter: 줄바꿈)"
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          disabled={disabled}
        />

        <div className={styles.actions}>
          {isStreaming ? (
            <button
              className={styles.bargeInButton}
              onClick={onBargeIn}
              title="0ms 발화 즉시 중단 (user_barge_in)"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              <span>발화 중단</span>
            </button>
          ) : (
            <button
              className={styles.sendButton}
              onClick={handleSend}
              disabled={disabled || !text.trim()}
              title="메시지 전송"
              aria-label="메시지 전송"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className={styles.footerHint}>
        <span>WebSocket 실시간 채널 (/api/v1/chat/ws)</span>
        <span>0ms Barge-in 지원 · Enter 전송</span>
      </div>
    </div>
  );
};
