"use client";

/**
 * Reading an answer aloud with the browser's own speech (Web Speech API).
 * Used when the server's AI voice is busy or out of its free quota: it's free,
 * has no limits and needs no network, but sounds like the device's voice.
 */

const ARABIC_SCRIPT = /[؀-ۿ]/;

export function canUseBrowserVoice(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}

function plainText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/(\*\*|__|`|~~|^#{1,6}\s*|^\s*[-*•]\s+)/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function pickVoice(language: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices();
  const matching = voices.filter((voice) => voice.lang.toLowerCase().startsWith(language));
  // Prefer natural/online voices where the browser offers them (e.g. Edge).
  return matching.find((voice) => /natural|online/i.test(voice.name)) ?? matching[0];
}

/** Starts speaking; returns a function that stops it. `onEnd` runs when it finishes or stops. */
export function speakInBrowser(text: string, onEnd: () => void): () => void {
  const synth = window.speechSynthesis;
  synth.cancel();
  const urdu = ARABIC_SCRIPT.test(text);
  const utterance = new SpeechSynthesisUtterance(plainText(text));
  const voice = pickVoice(urdu ? "ur" : "en") ?? (urdu ? pickVoice("hi") : undefined);
  if (voice) utterance.voice = voice;
  utterance.lang = voice?.lang ?? (urdu ? "ur-PK" : "en-US");
  utterance.onend = onEnd;
  utterance.onerror = onEnd;
  synth.speak(utterance);
  return () => {
    synth.cancel();
    onEnd();
  };
}
