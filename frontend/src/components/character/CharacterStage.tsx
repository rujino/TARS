import React, { useEffect } from 'react';
import styles from './CharacterStage.module.css';
import { useCharacterStore } from '@/stores/useCharacterStore';
import { CharacterSprite } from './CharacterSprite';
import { preloadCharacterAssets } from './characterAssets';

export const CharacterStage: React.FC = () => {
  const veraState = useCharacterStore((state) => state.veraState);
  const miuState = useCharacterStore((state) => state.miuState);
  const activeSpeaker = useCharacterStore((state) => state.activeSpeaker);

  // 컴포넌트 마운트 시 모든 캐릭터 상태 이미지 브라우저 메모리 사전 캐싱
  useEffect(() => {
    preloadCharacterAssets();
  }, []);

  const isVeraActive = activeSpeaker === 'vera' || veraState !== 'idle';
  const isMiuActive = activeSpeaker === 'miu' || miuState !== 'idle';

  return (
    <div className={styles.stageContainer} aria-hidden="true">
      {/* 1. 좌측 끝 베라 전신 (100% Height) */}
      <div
        className={`${styles.veraAnchor} ${
          isVeraActive ? styles.characterActive : isMiuActive ? styles.characterDimmed : ''
        }`}
      >
        <CharacterSprite speaker="vera" state={veraState} isActive={isVeraActive} />
      </div>

      {/* 2. 우측 끝 미우 전신 (100% Height) */}
      <div
        className={`${styles.miuAnchor} ${
          isMiuActive ? styles.characterActive : isVeraActive ? styles.characterDimmed : ''
        }`}
      >
        <CharacterSprite speaker="miu" state={miuState} isActive={isMiuActive} />
      </div>
    </div>
  );
};
