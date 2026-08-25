/**
 * TARS On-Device Web Speech API TTS Engine
 * Features:
 * - Real-time sentence boundary token buffering & queueing on [.!?\n]
 * - iOS Safari User Gesture pre-unlock audio pipeline warm-up
 * - 80-character run-on sentence chunking guard for Safari 15s freeze bug
 * - TARS signature baritone robotic cadence (Pitch: 0.8, Rate: 1.0)
 * - Mute, Stop, Volume, and Reset controls
 */
class TARSTTSEngine {
  constructor() {
    this.isMuted = false;
    this.isUnlocked = false;
    this.synth = typeof window !== 'undefined' ? window.speechSynthesis : null;
    this.queue = [];
    this.isSpeaking = false;
    this.textBuffer = '';

    // TARS Voice Parameters
    this.pitch = 0.75; // Low baritone robotic tone
    this.rate = 1.0;   // Measured tactical cadence
    this.volume = 1.0;
    this.koreanVoice = null;
    this.englishVoice = null;

    this.initVoices();
    this.setupUnlockListeners();
  }

  initVoices() {
    if (!this.synth) return;
    const updateVoices = () => {
      try {
        const voices = this.synth.getVoices() || [];
        if (!voices.length) return;

        // 1. Preferred Korean Male Voice (Minsu, Suhyeon, Google Korean Male, etc.)
        this.koreanVoice =
          voices.find(
            (v) =>
              v.lang.startsWith('ko') &&
              (v.name.includes('Minsu') ||
                v.name.includes('민수') ||
                v.name.includes('Suhyeon') ||
                v.name.includes('수현') ||
                v.name.includes('Male') ||
                v.name.includes('남성'))
          ) ||
          voices.find((v) => v.lang.startsWith('ko')) ||
          null;

        // 2. Preferred English Deep/Male Voice (Daniel, Alex, Fred, Aaron, David, etc.)
        this.englishVoice =
          voices.find(
            (v) =>
              v.lang.startsWith('en') && 현ㄷ
                (v.name.includes('Daniel') ||
                  v.name.includes('Alex') ||
                  v.name.includes('Fred') ||
                  v.name.includes('Aaron') ||
                  v.name.includes('Arthur') ||
                  v.name.includes('David') ||
                  v.name.includes('Oliver') ||
                  v.name.includes('Male') ||
                  v.name.includes('Natural'))
          ) ||
          voices.find(
            (v) =>
              v.lang.startsWith('en') &&
              !v.name.includes('Samantha') &&
              !v.name.includes('Victoria') &&
              !v.name.includes('Karen') &&
              !v.name.includes('Zira') &&
              !v.name.includes('Susan')
          ) ||
          voices.find((v) => v.lang.startsWith('en')) ||
          voices[0];

        console.log('[TTS] Voices initialized:', {
          ko: this.koreanVoice?.name || 'none',
          en: this.englishVoice?.name || 'none'
        });
      } catch (err) {
        console.warn('[TTS] Voice initialization warning:', err);
      }
    };

    updateVoices();
    if (this.synth.onvoiceschanged !== undefined) {
      this.synth.onvoiceschanged = updateVoices;
    }
  }

  getVoiceForText(text) {
    const isKorean = /[가-힣ㄱ-ㅎㅏ-ㅣ]/.test(text);
    if (isKorean) {
      // If voice is a known female voice (Yuna/Google/etc.), lower pitch to 0.48 for deep robotic tone
      const isMaleKo =
        this.koreanVoice &&
        (this.koreanVoice.name.includes('Minsu') ||
          this.koreanVoice.name.includes('민수') ||
          this.koreanVoice.name.includes('Suhyeon') ||
          this.koreanVoice.name.includes('수현') ||
          this.koreanVoice.name.includes('Male'));

      const koPitch = isMaleKo ? 0.75 : 0.48; // Modulate female voice down to robotic baritone

      return {
        voice: this.koreanVoice || this.englishVoice,
        lang: 'ko-KR',
        pitch: koPitch,
        rate: this.rate
      };
    }
    return {
      voice: this.englishVoice || this.koreanVoice,
      lang: 'en-US',
      pitch: this.pitch,
      rate: this.rate
    };
  }

  setupUnlockListeners() {
    if (typeof window === 'undefined') return;

    const unlock = () => {
      if (this.isUnlocked || !this.synth) return;
      try {
        // iOS Safari Audio Pipeline Warm-up via micro-utterance
        const utterance = new SpeechSynthesisUtterance(' ');
        utterance.volume = 0.01;
        utterance.rate = 10.0;
        this.synth.speak(utterance);
        this.isUnlocked = true;
      } catch (err) {
        console.warn('[TTS] Unlock gesture failed:', err);
      } finally {
        window.removeEventListener('click', unlock);
        window.removeEventListener('touchstart', unlock);
      }
    };

    window.addEventListener('click', unlock, { once: true });
    window.addEventListener('touchstart', unlock, { once: true });
  }

  setMute(mute) {
    this.isMuted = Boolean(mute);
    if (this.isMuted) {
      this.stop();
    }
  }

  toggleMute() {
    this.setMute(!this.isMuted);
    return this.isMuted;
  }

  stop() {
    if (this.synth) {
      try {
        this.synth.cancel();
      } catch (err) {
        console.warn('[TTS] Synth cancel error:', err);
      }
    }
    this.queue = [];
    this.textBuffer = '';
    this.isSpeaking = false;
  }

  /**
   * Push incoming streaming token chunk into the sentence accumulator
   */
  pushToken(token) {
    if (this.isMuted || !this.synth || !token) return;

    this.textBuffer += token;

    // Split on sentence boundaries: [.!?\n]
    const sentenceRegex = /^([\s\S]*?[.!?\n])\s*([\s\S]*)$/;
    let match = this.textBuffer.match(sentenceRegex);

    while (match) {
      const sentence = match[1].trim();
      this.textBuffer = match[2];

      if (sentence.length > 0) {
        this.enqueue(sentence);
      }
      match = this.textBuffer.match(sentenceRegex);
    }

    // Safety guard against long run-on sentences (>80 chars without punctuation for Safari 15s bug)
    if (this.textBuffer.length > 80) {
      const lastSpaceIdx = this.textBuffer.lastIndexOf(' ');
      if (lastSpaceIdx > 20) {
        const chunk = this.textBuffer.slice(0, lastSpaceIdx).trim();
        this.textBuffer = this.textBuffer.slice(lastSpaceIdx).trim();
        if (chunk.length > 0) {
          this.enqueue(chunk);
        }
      }
    }
  }

  /**
   * Flush remaining buffered text on stream completion
   */
  flush() {
    if (this.isMuted || !this.synth) return;
    const remaining = this.textBuffer.trim();
    if (remaining.length > 0) {
      this.enqueue(remaining);
      this.textBuffer = '';
    }
  }

  enqueue(text) {
    if (!text) return;

    // Strip markdown formatting symbols for clean acoustic speech
    const cleanText = text
      .replace(/```[\s\S]*?```/g, '') // remove code blocks
      .replace(/`([^`]+)`/g, '$1')     // inline code
      .replace(/[*_~#]/g, '')          // bold, italic, strikethrough, headers
      .replace(/\[(.*?)\]\(.*?\)/g, '$1') // link text only
      .replace(/>\s+/g, '')            // blockquotes
      .replace(/[-*+]\s+/g, '')        // list bullets
      .trim();

    if (!cleanText) return;

    this.queue.push(cleanText);
    this.processQueue();
  }

  processQueue() {
    if (this.isSpeaking || this.queue.length === 0 || this.isMuted || !this.synth) return;

    this.isSpeaking = true;
    const text = this.queue.shift();

    try {
      const voiceConfig = this.getVoiceForText(text);
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = voiceConfig.lang;
      utterance.pitch = voiceConfig.pitch;
      utterance.rate = voiceConfig.rate;
      utterance.volume = this.volume;

      if (voiceConfig.voice) {
        utterance.voice = voiceConfig.voice;
      }

      utterance.onend = () => {
        this.isSpeaking = false;
        this.processQueue();
      };

      utterance.onerror = (e) => {
        console.warn('[TTS] Utterance error:', e);
        this.isSpeaking = false;
        this.processQueue();
      };

      this.synth.speak(utterance);
    } catch (err) {
      console.warn('[TTS] SpeechSynthesis speak exception:', err);
      this.isSpeaking = false;
      this.processQueue();
    }
  }
}

if (typeof window !== 'undefined') {
  window.TARSTTSEngine = TARSTTSEngine;
}
