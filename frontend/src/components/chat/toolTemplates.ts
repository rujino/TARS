/**
 * 도구 실행 시 캐릭터 상황극 말풍선 문구 템플릿
 * 추후 손쉬운 커스텀 및 다국어 확장을 위해 분리된 상수 모듈
 */

export interface ToolMessageTemplate {
  running: string;
  completed: string;
  failed: string;
}

export const TOOL_MESSAGE_TEMPLATES: Record<
  string, // 도구 키워드
  Record<'vera' | 'miu', ToolMessageTemplate>
> = {
  calendar: {
    vera: {
      running: '📋 Google Calendar 일정을 꼼꼼히 확인하고 있습니다...',
      completed: '✨ 일정 조회를 완료하였습니다. 바로 보고드리겠습니다.',
      failed: '⚠️ 일정 확인 중 차질이 생겼습니다. 다시 확인해 보겠습니다.',
    },
    miu: {
      running: '🐾 달력을 뒤적뒤적 찾는 중이에요! 잠시만 기다려주세요~',
      completed: '🎉 찾았다냥! 일정을 전부 확인했어요!',
      failed: '😿 으앙, 달력을 보다가 깜빡 놓쳤어요...',
    },
  },
  gmail: {
    vera: {
      running: '✉️ 수신된 서신(Gmail)을 정돈하며 관련 내용을 확인 중입니다...',
      completed: '✨ 메일 조회가 완료되었습니다.',
      failed: '⚠️ 서신을 확인하는 과정에서 지연이 발생했습니다.',
    },
    miu: {
      running: '📬 편지함을 샤샤삭 살펴보는 중이에요!',
      completed: '💌 메일 확인 끝! 중요한 소식이 있을까요?',
      failed: '😿 편지함이 굳게 닫혀 있어서 못 봤어요...',
    },
  },
  docs: {
    vera: {
      running: '📑 보관된 서류(Google Docs)를 정밀 검토하고 있습니다...',
      completed: '✨ 문서 확인 및 정리를 마쳤습니다.',
      failed: '⚠️ 문서를 열람하는 도중 문제가 발생했습니다.',
    },
    miu: {
      running: '📖 서류철을 열심히 넘겨보고 있어요!',
      completed: '💡 문서 내용을 다 읽었어요! 에헴~',
      failed: '😿 글씨가 너무 빽빽해서 읽다가 길을 잃었어요...',
    },
  },
  search: {
    vera: {
      running: '🔍 외부 정보망 및 최신 자료를 신속히 검색하고 있습니다...',
      completed: '✨ 관련 정보를 취합하여 정리하였습니다.',
      failed: '⚠️ 정보를 검색하는 과정에서 오류가 발생했습니다.',
    },
    miu: {
      running: '🔎 바깥 세상 소식을 쫑긋 귀 기울여 알아오는 중이에요!',
      completed: '🌟 궁금했던 내용들을 쏙쏙 알아왔어요!',
      failed: '😿 잉... 찾아보려고 했는데 바람에 날아갔나 봐요.',
    },
  },
  default: {
    vera: {
      running: '⚙️ 요청하신 업무를 메모보드에 기록하며 수행하고 있습니다...',
      completed: '✨ 요청하신 처리가 안전하게 완료되었습니다.',
      failed: '⚠️ 업무 수행 중 예기치 않은 오류가 발생했습니다.',
    },
    miu: {
      running: '🐾 미우가 뚝딱뚝딱 처리 중이에요! 조금만 기다려주세요!',
      completed: '🎉 미션 클리어! 미우가 해냈어요~',
      failed: '😿 흑... 도중에 실수가 있었나 봐요...',
    },
  },
};

/**
 * 도구 이름과 화자, 실행 상태를 기반으로 최적의 상황극 대사를 반환
 */
export const getToolSpeech = (
  toolName: string,
  speaker: 'vera' | 'miu' = 'vera',
  status: 'running' | 'completed' | 'failed' = 'running'
): string => {
  const lowerName = (toolName || '').toLowerCase();
  let category = 'default';

  if (lowerName.includes('calendar') || lowerName.includes('event')) {
    category = 'calendar';
  } else if (lowerName.includes('mail') || lowerName.includes('gmail')) {
    category = 'gmail';
  } else if (lowerName.includes('doc') || lowerName.includes('file')) {
    category = 'docs';
  } else if (lowerName.includes('search') || lowerName.includes('web')) {
    category = 'search';
  }

  const templates = TOOL_MESSAGE_TEMPLATES[category] || TOOL_MESSAGE_TEMPLATES.default;
  const speakerTemplates = templates[speaker] || templates.vera;
  return speakerTemplates[status] || speakerTemplates.running;
};
