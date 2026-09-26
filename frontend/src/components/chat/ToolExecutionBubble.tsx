import React from 'react';
import styles from './ToolExecutionBubble.module.css';
import { getToolSpeech } from './toolTemplates';

export interface ToolExecutionState {
  tool: string;
  speaker: 'vera' | 'miu';
  status: 'running' | 'completed' | 'failed';
  callId?: string;
  resultSummary?: string;
}

interface ToolExecutionBubbleProps {
  execution: ToolExecutionState;
}

export const ToolExecutionBubble: React.FC<ToolExecutionBubbleProps> = ({ execution }) => {
  const isVera = execution.speaker === 'vera';
  const speech = getToolSpeech(execution.tool, execution.speaker, execution.status);

  return (
    <div
      className={`${styles.bubbleContainer} ${
        isVera ? styles.alignLeft : styles.alignRight
      }`}
    >
      <div
        className={`${styles.cardBody} ${
          isVera
            ? `${styles.veraBorder} ${styles.veraTail}`
            : `${styles.miuBorder} ${styles.miuTail}`
        }`}
      >
        <div className={styles.headerRow}>
          <div
            className={`${styles.speakerBadge} ${
              isVera ? styles.badgeVera : styles.badgeMiu
            }`}
          >
            <span>{isVera ? '🏛️ 베라' : '🐾 미우'}</span>
            <span>· 도구 수행</span>
          </div>
          <span className={styles.toolBadge}>{execution.tool}</span>
        </div>

        <div className={styles.speechText}>
          {execution.status === 'running' && (
            <div
              className={`${styles.spinner} ${
                isVera ? styles.spinnerVera : styles.spinnerMiu
              }`}
            />
          )}
          <span>{speech}</span>
        </div>
      </div>
    </div>
  );
};
