import React, { useState } from 'react';
import type { CharacterActionState } from '@/stores/useCharacterStore';
import { CHARACTER_IMAGE_MAP } from './characterAssets';
import { CharacterSilhouette } from './CharacterSilhouette';

interface CharacterSpriteProps {
  speaker: 'vera' | 'miu';
  state: CharacterActionState;
  isActive: boolean;
}

export const CharacterSprite: React.FC<CharacterSpriteProps> = ({
  speaker,
  state,
  isActive,
}) => {
  const [hasError, setHasError] = useState(false);

  // 로딩 실패 시 기존 SVG 실루엣으로 안전하게 폴백
  if (hasError) {
    return <CharacterSilhouette speaker={speaker} state={state} isActive={isActive} />;
  }

  const imageUrl = CHARACTER_IMAGE_MAP[speaker][state] || CHARACTER_IMAGE_MAP[speaker].idle;
  const isVera = speaker === 'vera';

  return (
    <div
      style={{
        width: 'auto',
        height: '100%',
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
        position: 'relative',
        transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        filter: 'none',
        transform: isActive ? 'scale(1.02)' : 'scale(1.0)',
        opacity: 1,
      }}
    >
      <img
        src={imageUrl}
        alt={`${speaker} (${state})`}
        onError={() => setHasError(true)}
        style={{
          width: 'auto',
          height: '100%',
          objectFit: 'contain',
          objectPosition: 'bottom',
          userSelect: 'none',
          pointerEvents: 'none',
          transition: 'opacity 0.25s ease',
        }}
        draggable={false}
      />
    </div>
  );
};
