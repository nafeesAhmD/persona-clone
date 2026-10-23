/**
 * Energy-based voice activity detection (pure). Fed the microphone's RMS level every
 * frame (from an AnalyserNode), it decides when an utterance starts and ends, so each
 * utterance can be sent as one recording.
 *
 *   silence ──(level ≥ start threshold for startMs)──▶ speech  [speech_start]
 *   speech  ──(level < end threshold for endSilenceMs)──▶ silence [speech_end | too_short]
 *   speech  ──(longer than maxUtteranceMs)──▶ silence [max_length]
 *
 * While the clone is speaking the start threshold is higher (`bargeInThreshold`), so
 * its own voice leaking from the speakers (echo cancellation isn't perfect) doesn't
 * count as the user, but the user talking over it does: that is the barge-in.
 */

export interface VadConfig {
  /** RMS level (0..1) that counts as speech. */
  startThreshold: number;
  /** Level needed to start speech while the clone is talking (barge-in). */
  bargeInThreshold: number;
  /** Speech ends when the level stays below startThreshold × endRatio for this long. */
  endSilenceMs: number;
  endRatio: number;
  /** Level must stay above the threshold this long to start (ignores clicks). */
  startMs: number;
  /** Shorter utterances are dropped (coughs, clicks). */
  minSpeechMs: number;
  maxUtteranceMs: number;
}

export const DEFAULT_VAD: VadConfig = {
  startThreshold: 0.02,
  bargeInThreshold: 0.06,
  endSilenceMs: 800,
  endRatio: 0.6,
  startMs: 120,
  minSpeechMs: 300,
  maxUtteranceMs: 30_000,
};

export interface VadState {
  phase: "silence" | "speech";
  /** Time above the threshold while still in silence. */
  aboveMs: number;
  /** Length of the current utterance (including the trailing silence so far). */
  speechMs: number;
  silenceMs: number;
}

export type VadEvent = "speech_start" | "speech_end" | "too_short" | "max_length" | null;

export const INITIAL_VAD: VadState = { phase: "silence", aboveMs: 0, speechMs: 0, silenceMs: 0 };

/** One frame: `level` is the RMS (0..1), `dtMs` the time since the previous frame. */
export function vadStep(
  state: VadState,
  level: number,
  dtMs: number,
  aiSpeaking: boolean,
  config: VadConfig = DEFAULT_VAD,
): { state: VadState; event: VadEvent } {
  if (state.phase === "silence") {
    const threshold = aiSpeaking ? config.bargeInThreshold : config.startThreshold;
    if (level < threshold) return { state: { ...INITIAL_VAD }, event: null };
    const aboveMs = state.aboveMs + dtMs;
    if (aboveMs < config.startMs) return { state: { ...state, aboveMs }, event: null };
    return { state: { phase: "speech", aboveMs: 0, speechMs: aboveMs, silenceMs: 0 }, event: "speech_start" };
  }

  const speechMs = state.speechMs + dtMs;
  const quiet = level < config.startThreshold * config.endRatio;
  const silenceMs = quiet ? state.silenceMs + dtMs : 0;
  if (speechMs >= config.maxUtteranceMs) return { state: { ...INITIAL_VAD }, event: "max_length" };
  if (silenceMs >= config.endSilenceMs) {
    const spoken = speechMs - silenceMs;
    return { state: { ...INITIAL_VAD }, event: spoken >= config.minSpeechMs ? "speech_end" : "too_short" };
  }
  return { state: { phase: "speech", aboveMs: 0, speechMs, silenceMs }, event: null };
}

/** RMS of time-domain samples from AnalyserNode.getFloatTimeDomainData (−1..1). */
export function rms(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}
