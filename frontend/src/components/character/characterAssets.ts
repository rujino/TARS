import type { CharacterActionState } from '@/stores/useCharacterStore';

export const ASSET_BASE_URL =
  (import.meta.env.VITE_ASSETS_BASE_URL as string) ||
  'http://localhost:8888/buckets/tars-assets/characters';

export const CHARACTER_IMAGE_MAP: Record<
  'vera' | 'miu',
  Record<CharacterActionState, string>
> = {
  vera: {
    idle: `${ASSET_BASE_URL}/vera/maid1-idle.png`,
    tool_use: `${ASSET_BASE_URL}/vera/maid1-tools.png`,
    speaking: `${ASSET_BASE_URL}/vera/maid1-smile.png`,
    thinking: `${ASSET_BASE_URL}/vera/maid1-idle.png`,
    interrupted: `${ASSET_BASE_URL}/vera/maid1-embarrassed.png`,
  },
  miu: {
    idle: `${ASSET_BASE_URL}/miu/maid2-idle.png`,
    tool_use: `${ASSET_BASE_URL}/miu/maid2-hugging.png`,
    speaking: `${ASSET_BASE_URL}/miu/maid2-happy.png`,
    thinking: `${ASSET_BASE_URL}/miu/maid2-hugging.png`,
    interrupted: `${ASSET_BASE_URL}/miu/maid2-annoyed.png`,
  },
};

/**
 * 앱 기동 시 모든 캐릭터 상태 이미지를 메모리에 사전 로딩하여 깜빡임 방지
 */
export const preloadCharacterAssets = (): void => {
  if (typeof window === 'undefined') return;

  const urls: string[] = [
    ...Object.values(CHARACTER_IMAGE_MAP.vera),
    ...Object.values(CHARACTER_IMAGE_MAP.miu),
  ];

  urls.forEach((url) => {
    const img = new Image();
    img.src = url;
  });
};
