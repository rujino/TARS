import React from 'react';
import type { CharacterActionState } from '@/stores/useCharacterStore';

interface CharacterSilhouetteProps {
  speaker: 'vera' | 'miu';
  state: CharacterActionState;
  isActive: boolean;
}

export const CharacterSilhouette: React.FC<CharacterSilhouetteProps> = ({
  speaker,
  state,
  isActive,
}) => {
  const isVera = speaker === 'vera';

  // 베라(슬레이트 인디고) vs 미우(코랄 오렌지) 테마 컬러
  const primaryGradientId = isVera ? 'veraGradient' : 'miuGradient';

  return (
    <svg
      viewBox="0 0 160 520"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMax meet"
      style={{
        filter: 'none',
        transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        transform: isActive ? 'scale(1.02)' : 'scale(1.0)',
        opacity: 1,
      }}
    >
      <defs>
        {/* 베라 그라데이션 */}
        <linearGradient id="veraGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#818cf8" />
          <stop offset="40%" stopColor="#4f46e5" />
          <stop offset="100%" stopColor="#1e1b4b" />
        </linearGradient>

        {/* 미우 그라데이션 */}
        <linearGradient id="miuGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#fb923c" />
          <stop offset="40%" stopColor="#ea580c" />
          <stop offset="100%" stopColor="#431407" />
        </linearGradient>

        {/* 클립보드/메모보드 그라데이션 */}
        <linearGradient id="clipboardGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#f8fafc" />
          <stop offset="100%" stopColor="#94a3b8" />
        </linearGradient>
      </defs>

      {/* 1. 베라(Vera: 우아하고 차분한 메이드장) 실루엣 */}
      {isVera ? (
        <g id="vera-group">
          {/* 헤드드레스 (카츄샤) */}
          <path
            d="M 55 58 Q 80 42 105 58 Q 80 48 55 58 Z"
            fill="#ffffff"
            opacity="0.85"
          />

          {/* 머리 실루엣 (긴 생머리) */}
          <path
            d="M 50 68 Q 80 35 110 68 Q 118 100 115 170 Q 80 180 45 170 Q 42 100 50 68 Z"
            fill={`url(#${primaryGradientId})`}
          />

          {/* 얼굴/목 윤곽 */}
          <ellipse cx="80" cy="85" rx="22" ry="24" fill={`url(#${primaryGradientId})`} opacity="0.95" />
          <rect x="74" y="105" width="12" height="18" rx="4" fill={`url(#${primaryGradientId})`} />

          {/* 상체 & 메이드복 칼라 */}
          <path
            d="M 52 120 L 108 120 L 118 200 L 42 200 Z"
            fill={`url(#${primaryGradientId})`}
          />
          {/* 흰색 앞치마 빕(Bib) & 리본 */}
          <polygon points="66,120 94,120 86,190 74,190" fill="#ffffff" opacity="0.8" />
          <circle cx="80" cy="126" r="4" fill="#312e81" />

          {/* 팔 & 손 포즈 (상태에 따라 변화) */}
          {state === 'tool_use' ? (
            /* 📋 도구 사용 중: 한 손에 메모보드 들고 펜으로 적는 포즈 */
            <g id="vera-tool-use-arms">
              {/* 오른쪽 팔이 몸 앞으로 뻗어 메모보드를 받침 */}
              <path d="M 46 130 Q 30 160 50 185" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              {/* 메모보드(클립보드) 사각형 */}
              <rect x="36" y="150" width="38" height="52" rx="4" fill="url(#clipboardGrad)" stroke="#1e1b4b" strokeWidth="2" />
              <rect x="46" y="146" width="18" height="8" rx="2" fill="#475569" />
              {/* 서류 메모선들 */}
              <line x1="42" y1="162" x2="68" y2="162" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
              <line x1="42" y1="170" x2="64" y2="170" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
              <line x1="42" y1="178" x2="60" y2="178" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
              <line x1="42" y1="186" x2="66" y2="186" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
              {/* 펜을 든 왼손 */}
              <path d="M 114 130 Q 105 165 72 175" stroke="#818cf8" strokeWidth="9" strokeLinecap="round" fill="none" />
              <line x1="72" y1="175" x2="64" y2="170" stroke="#fbbf24" strokeWidth="3" strokeLinecap="round" />
            </g>
          ) : state === 'speaking' ? (
            /* 🗣️ 발화 중: 한 손을 가슴에 얹고 다른 손을 살짝 뻗어 설명 */
            <g id="vera-speaking-arms">
              <path d="M 48 130 Q 60 160 74 155" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              <path d="M 112 130 Q 128 155 125 175" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              <circle cx="125" cy="175" r="5" fill="#c7d2fe" />
            </g>
          ) : state === 'interrupted' ? (
            /* ❗ 놀람: 양손을 가슴께로 올리며 살짝 흠칫 */
            <g id="vera-interrupted-arms">
              <path d="M 46 130 Q 40 145 56 142" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              <path d="M 114 130 Q 120 145 104 142" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              {/* 머리 위 느낌표 이모지 */}
              <text x="80" y="32" textAnchor="middle" fontSize="24" fill="#fbbf24">❗</text>
            </g>
          ) : (
            /* 🍃 기본 대기 (idle/thinking): 두 손을 단정히 앞으로 모음 */
            <g id="vera-idle-arms">
              <path d="M 48 130 Q 55 175 75 180" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              <path d="M 112 130 Q 105 175 85 180" stroke="#818cf8" strokeWidth="10" strokeLinecap="round" fill="none" />
              <ellipse cx="80" cy="180" rx="9" ry="6" fill="#c7d2fe" />
            </g>
          )}

          {/* 허리 리본 & 벨트 */}
          <rect x="54" y="195" width="52" height="10" rx="3" fill="#312e81" />
          <ellipse cx="80" cy="200" rx="7" ry="5" fill="#ffffff" opacity="0.9" />

          {/* 하단 롱스커트 (전신 100% Height) */}
          <path
            d="M 54 205 Q 80 215 106 205 L 138 480 Q 80 500 22 480 Z"
            fill={`url(#${primaryGradientId})`}
          />
          {/* 앞치마 프릴 레이어 */}
          <path
            d="M 64 205 L 96 205 L 114 420 Q 80 435 46 420 Z"
            fill="#ffffff"
            opacity="0.75"
          />

          {/* 발/구두 */}
          <ellipse cx="65" cy="488" rx="14" ry="7" fill="#0f172a" />
          <ellipse cx="95" cy="488" rx="14" ry="7" fill="#0f172a" />

          {/* 캐릭터 이름 뱃지 (발밑) */}
          <rect x="42" y="500" width="76" height="18" rx="9" fill="#1e1b4b" stroke="#818cf8" strokeWidth="1" />
          <text x="80" y="513" textAnchor="middle" fontSize="10" fill="#c7d2fe" fontWeight="700">
            VERA
          </text>
        </g>
      ) : (
        /* 2. 미우(Miu: 생기 넘치는 발랄한 보조 메이드) 실루엣 */
        <g id="miu-group">
          {/* 리본 카츄샤 */}
          <path
            d="M 58 60 Q 80 46 102 60 Q 80 52 58 60 Z"
            fill="#ffffff"
            opacity="0.85"
          />
          <polygon points="48,52 60,46 54,62" fill="#ea580c" />
          <polygon points="112,52 100,46 106,62" fill="#ea580c" />

          {/* 발랄한 트윈테일 헤어 */}
          <path
            d="M 52 70 Q 80 40 108 70 Q 116 110 110 140 Q 80 135 50 140 Q 44 110 52 70 Z"
            fill={`url(#${primaryGradientId})`}
          />
          {/* 좌우 트윈테일 묶음 */}
          <path d="M 48 78 Q 24 100 28 150 Q 40 130 50 95 Z" fill={`url(#${primaryGradientId})`} />
          <path d="M 112 78 Q 136 100 132 150 Q 120 130 110 95 Z" fill={`url(#${primaryGradientId})`} />

          {/* 얼굴 & 목 */}
          <ellipse cx="80" cy="88" rx="21" ry="23" fill={`url(#${primaryGradientId})`} opacity="0.95" />
          <rect x="74" y="107" width="12" height="16" rx="4" fill={`url(#${primaryGradientId})`} />

          {/* 상체 & 메이드복 */}
          <path
            d="M 54 122 L 106 122 L 114 195 L 46 195 Z"
            fill={`url(#${primaryGradientId})`}
          />
          {/* 코랄 보우타이 & 앞치마 */}
          <polygon points="68,122 92,122 84,185 76,185" fill="#ffffff" opacity="0.8" />
          <circle cx="80" cy="128" r="4" fill="#9a3412" />

          {/* 팔 & 손 포즈 */}
          {state === 'tool_use' ? (
            /* 📝 도구 사용 중: 양손으로 작은 수첩을 쥐고 열심히 메모 */
            <g id="miu-tool-use-arms">
              <path d="M 48 132 Q 62 165 72 160" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <path d="M 112 132 Q 98 165 88 160" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              {/* 작은 미니 수첩 */}
              <rect x="68" y="148" width="24" height="30" rx="3" fill="url(#clipboardGrad)" stroke="#431407" strokeWidth="2" />
              <line x1="72" y1="156" x2="88" y2="156" stroke="#ea580c" strokeWidth="1.5" />
              <line x1="72" y1="162" x2="86" y2="162" stroke="#ea580c" strokeWidth="1.5" />
              <line x1="72" y1="168" x2="84" y2="168" stroke="#ea580c" strokeWidth="1.5" />
            </g>
          ) : state === 'speaking' ? (
            /* 🗣️ 발화 중: 두 손을 펴서 쫑알쫑알 제스처 */
            <g id="miu-speaking-arms">
              <path d="M 48 132 Q 35 155 42 170" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <path d="M 112 132 Q 125 155 118 170" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <circle cx="42" cy="170" r="5" fill="#ffedd5" />
              <circle cx="118" cy="170" r="5" fill="#ffedd5" />
            </g>
          ) : state === 'interrupted' ? (
            /* 💧 땀방울 & 두 손 번쩍 들고 깜짝 놀람 */
            <g id="miu-interrupted-arms">
              <path d="M 48 132 Q 30 115 38 100" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <path d="M 112 132 Q 130 115 122 100" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <circle cx="38" cy="100" r="5" fill="#ffedd5" />
              <circle cx="122" cy="100" r="5" fill="#ffedd5" />
              {/* 머리 위 땀방울 */}
              <text x="80" y="32" textAnchor="middle" fontSize="22" fill="#38bdf8">💧</text>
            </g>
          ) : (
            /* 🍃 기본 대기 (idle): 살짝 장난치듯 양손을 허리에 */
            <g id="miu-idle-arms">
              <path d="M 48 132 Q 38 160 52 175" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <path d="M 112 132 Q 122 160 108 175" stroke="#fb923c" strokeWidth="9" strokeLinecap="round" fill="none" />
              <ellipse cx="52" cy="175" rx="5" ry="4" fill="#ffedd5" />
              <ellipse cx="108" cy="175" rx="5" ry="4" fill="#ffedd5" />
            </g>
          )}

          {/* 허리 밴드 & 미니 리본 */}
          <rect x="56" y="192" width="48" height="9" rx="3" fill="#7c2d12" />
          <circle cx="80" cy="196" r="4" fill="#ffffff" />

          {/* 숏 플리츠 스커트 (활동적인 실루엣) */}
          <path
            d="M 56 200 Q 80 208 104 200 L 126 340 Q 80 355 34 340 Z"
            fill={`url(#${primaryGradientId})`}
          />
          {/* 미니 앞치마 */}
          <path
            d="M 64 200 L 96 200 L 106 310 Q 80 320 54 310 Z"
            fill="#ffffff"
            opacity="0.8"
          />

          {/* 다리 & 롱 삭스 */}
          <rect x="62" y="340" width="12" height="135" rx="5" fill="#1c1917" />
          <rect x="86" y="340" width="12" height="135" rx="5" fill="#1c1917" />

          {/* 구두 */}
          <ellipse cx="68" cy="482" rx="12" ry="6" fill="#431407" />
          <ellipse cx="92" cy="482" rx="12" ry="6" fill="#431407" />

          {/* 캐릭터 이름 뱃지 */}
          <rect x="44" y="500" width="72" height="18" rx="9" fill="#431407" stroke="#fb923c" strokeWidth="1" />
          <text x="80" y="513" textAnchor="middle" fontSize="10" fill="#ffedd5" fontWeight="700">
            MIU
          </text>
        </g>
      )}
    </svg>
  );
};
