import type { ChatMessageResponse } from '@/types/chat.types';

/**
 * Remove redundant speaker prefixes like "베라:", "🏛️ 베라:", "미우:", "🐾 미우:"
 * from the beginning of message content when rendered inside a labeled bubble.
 */
export function cleanSpeakerPrefix(content: string, speaker: string): string {
  const s = speaker.toLowerCase();
  if (s === 'vera') {
    return content.replace(/^(?:\[?(?:🏛️\s*)?(?:베라|Vera)\]?)\s*:\s*/i, '');
  }
  if (s === 'miu') {
    return content.replace(/^(?:\[?(?:🐾\s*)?(?:미우|Miu)\]?)\s*:\s*/i, '');
  }
  return content;
}

/**
 * Split a combined assistant message containing turns from multiple speakers
 * (e.g. "베라: ...\n\n미우: ...") into individual ChatMessageResponse turns
 * so that both agents have their own distinct speech bubble.
 */
export function splitMultiSpeakerMessage(msg: ChatMessageResponse): ChatMessageResponse[] {
  if (msg.role !== 'assistant' || !msg.content) return [msg];

  const regex = /(?:^|\n+)(?:\[?(?:🏛️\s*)?(?:베라|Vera)\]?|\[?(?:🐾\s*)?(?:미우|Miu)\]?)\s*:\s*/gi;
  const matches = [...msg.content.matchAll(regex)];

  if (matches.length === 0) {
    return [msg];
  }

  // If there is only 1 match at the very beginning of the message
  if (matches.length === 1 && matches[0].index === 0) {
    const matchedPrefix = matches[0][0].toLowerCase();
    const detectedSpeaker =
      matchedPrefix.includes('미우') || matchedPrefix.includes('miu') ? 'miu' : 'vera';
    const cleaned = msg.content.slice(matches[0][0].length).trim();
    return [
      {
        ...msg,
        speaker: msg.speaker || detectedSpeaker,
        content: cleaned || msg.content,
      },
    ];
  }

  const result: ChatMessageResponse[] = [];

  // If there is introductory text before the first speaker marker
  if (matches[0].index > 0) {
    const intro = msg.content.slice(0, matches[0].index).trim();
    if (intro) {
      result.push({
        ...msg,
        id: `${msg.id}-intro`,
        speaker: msg.speaker || 'vera',
        content: intro,
      });
    }
  }

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const startIndex = match.index + match[0].length;
    const endIndex = i + 1 < matches.length ? matches[i + 1].index : msg.content.length;
    const chunkContent = msg.content.slice(startIndex, endIndex).trim();

    const matchedPrefix = match[0].toLowerCase();
    const speaker =
      matchedPrefix.includes('미우') || matchedPrefix.includes('miu') ? 'miu' : 'vera';

    if (chunkContent) {
      result.push({
        ...msg,
        id: `${msg.id}-speaker-${i}`,
        speaker,
        content: chunkContent,
      });
    }
  }

  return result.length > 0 ? result : [msg];
}
