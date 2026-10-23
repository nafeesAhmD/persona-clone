/**
 * Voice turn state machine (pure: no React, no DOM), shared by the chat and tested
 * in tests/voiceStates.test.ts.
 *
 *   Idle ─tap─▶ Requesting ─granted─▶ Listening ─stop─▶ Uploading ─sent─▶ Transcribing
 *     ▲                                   │ time limit                         │ text
 *     │                                   ▼                                    ▼
 *     │                              Recorded (wait for "Send")            Thinking
 *     │                                                                        │ answer
 *     │                                                     (voice reply) ┌────┴────┐ (text / avatar)
 *     │                                                                   ▼         ▼
 *     └──── reset / cancel ◀──── Complete ◀── voice ready ── Generating Voice    Complete
 *
 * Any step can fail into Error (with a code). Recording never starts without a tap,
 * and audio is only uploaded after the user tapped Stop/Send: reaching the time
 * limit parks the recording in "recorded" until the user sends or discards it.
 */

export type VoiceStage =
  | "idle"
  | "requesting"
  | "listening"
  | "recorded"
  | "uploading"
  | "transcribing"
  | "thinking"
  | "generating_voice"
  | "complete"
  | "error";

export type VoiceErrorCode =
  | "unsupported"
  | "insecure_context"
  | "permission_denied"
  | "no_microphone"
  | "microphone_busy"
  | "recording_failed"
  | "empty_recording"
  | "upload_failed"
  | "offline"
  | "too_large"
  | "provider_busy"
  | "provider_unavailable"
  | "not_allowed"
  | "unknown";

export interface VoiceState {
  stage: VoiceStage;
  error: VoiceErrorCode | null;
  /** Optional server-provided detail shown under the friendly message. */
  detail: string | null;
}

export type VoiceEvent =
  | { type: "tap_record" }
  | { type: "permission_granted" }
  | { type: "limit_reached" }
  | { type: "upload_started" }
  | { type: "uploaded" }
  | { type: "transcribed" }
  | { type: "answer_ready"; speak: boolean }
  | { type: "voice_ready" }
  | { type: "fail"; code: VoiceErrorCode; detail?: string | null }
  | { type: "cancel" }
  | { type: "reset" };

export const INITIAL_VOICE_STATE: VoiceState = { stage: "idle", error: null, detail: null };

const at = (stage: VoiceStage): VoiceState => ({ stage, error: null, detail: null });

/** Stages from which a new recording may start (always after a tap). */
const RESTARTABLE: ReadonlySet<VoiceStage> = new Set(["idle", "complete", "error"]);

export function voiceReducer(state: VoiceState, event: VoiceEvent): VoiceState {
  switch (event.type) {
    case "tap_record":
      return RESTARTABLE.has(state.stage) ? at("requesting") : state;
    case "permission_granted":
      return state.stage === "requesting" ? at("listening") : state;
    case "limit_reached":
      return state.stage === "listening" ? at("recorded") : state;
    case "upload_started":
      // From a live recording (Stop tapped), a parked one (Send tapped) or a retry after an error.
      return state.stage === "listening" || state.stage === "recorded" || state.stage === "error"
        ? at("uploading")
        : state;
    case "uploaded":
      return state.stage === "uploading" ? at("transcribing") : state;
    case "transcribed":
      return state.stage === "uploading" || state.stage === "transcribing" ? at("thinking") : state;
    case "answer_ready":
      if (state.stage !== "thinking") return state;
      return at(event.speak ? "generating_voice" : "complete");
    case "voice_ready":
      return state.stage === "generating_voice" ? at("complete") : state;
    case "fail":
      return { stage: "error", error: event.code, detail: event.detail ?? null };
    case "cancel":
      return isCancellable(state.stage) ? INITIAL_VOICE_STATE : state;
    case "reset":
      return INITIAL_VOICE_STATE;
    default:
      return state;
  }
}

export interface StageInfo {
  label: string;
  /** Decorative glyph; the label always carries the meaning (never color or icon alone). */
  icon: string;
  /** Work is in progress (show a spinner / disable the composer). */
  busy: boolean;
}

export const STAGE_INFO: Record<VoiceStage, StageInfo> = {
  idle: { label: "Ready", icon: "🎤", busy: false },
  requesting: { label: "Waiting for microphone permission…", icon: "🔐", busy: true },
  listening: { label: "Listening…", icon: "🔴", busy: true },
  recorded: { label: "Time limit reached. Send or discard your recording.", icon: "⏸", busy: true },
  uploading: { label: "Uploading recording…", icon: "⬆", busy: true },
  transcribing: { label: "Transcribing…", icon: "📝", busy: true },
  thinking: { label: "Thinking…", icon: "💭", busy: true },
  generating_voice: { label: "Generating voice…", icon: "🔊", busy: true },
  complete: { label: "Complete", icon: "✓", busy: false },
  error: { label: "Voice message failed", icon: "⚠", busy: false },
};

/** Whether Cancel is offered: before the transcript is in, the turn can be thrown away. */
export function isCancellable(stage: VoiceStage): boolean {
  return stage === "requesting" || stage === "listening" || stage === "recorded" || stage === "uploading" || stage === "transcribing";
}

export function canStartRecording(state: VoiceState): boolean {
  return RESTARTABLE.has(state.stage);
}

/** A failed upload / transcription can be retried with the same recording (on tap only). */
export function canRetryRecording(code: VoiceErrorCode | null): boolean {
  return code === "upload_failed" || code === "offline" || code === "provider_busy" || code === "provider_unavailable";
}

export interface VoiceEnvironment {
  secureContext: boolean;
  hasGetUserMedia: boolean;
  hasMediaRecorder: boolean;
}

/** null when recording can work here; otherwise why not. */
export function checkVoiceSupport(env: VoiceEnvironment): VoiceErrorCode | null {
  if (!env.secureContext) return "insecure_context";
  if (!env.hasGetUserMedia || !env.hasMediaRecorder) return "unsupported";
  return null;
}

/** Maps getUserMedia / MediaRecorder DOMException names. */
export function mediaErrorCode(name: string | undefined): VoiceErrorCode {
  switch (name) {
    case "NotAllowedError":
    case "PermissionDeniedError":
      return "permission_denied";
    case "SecurityError":
      return "insecure_context";
    case "NotFoundError":
    case "DevicesNotFoundError":
    case "OverconstrainedError":
      return "no_microphone";
    case "NotReadableError":
    case "TrackStartError":
    case "AbortError":
      return "microphone_busy";
    case "NotSupportedError":
      return "unsupported";
    default:
      return "recording_failed";
  }
}

/**
 * Maps an API failure. `kind` is ApiError.kind when lib/api provides it
 * ("offline" | "timeout" | "unavailable" | "rate_limit" | ...); status is the fallback.
 */
export function httpErrorCode(status: number | undefined, kind?: string): VoiceErrorCode {
  if (kind === "offline") return "offline";
  if (kind === "rate_limit" || kind === "usage_limit" || status === 429) return "provider_busy";
  if (kind === "unavailable" || kind === "timeout" || status === 502 || status === 503 || status === 504) {
    return "provider_unavailable";
  }
  if (status === 413) return "too_large";
  if (kind === "auth" || kind === "forbidden" || status === 401 || status === 403) return "not_allowed";
  if (status === undefined) return "upload_failed";
  if (status >= 500) return "provider_unavailable";
  return "unknown";
}

export function voiceErrorMessage(code: VoiceErrorCode): string {
  switch (code) {
    case "unsupported":
      return "This browser can't record audio. Try a recent Chrome, Edge, Firefox or Safari, or type your message.";
    case "insecure_context":
      return "The microphone only works on a secure (https) page. Open the app over https, or type your message.";
    case "permission_denied":
      return "Microphone permission was denied. Allow the microphone for this site in your browser or phone settings, then tap the mic again.";
    case "no_microphone":
      return "No microphone was found on this device.";
    case "microphone_busy":
      return "The microphone is being used by another app (for example a call). Close it and try again.";
    case "recording_failed":
      return "Recording failed. Please try again.";
    case "empty_recording":
      return "We couldn't hear anything. Hold the phone closer and try again.";
    case "upload_failed":
      return "The recording couldn't be uploaded. Check your connection and try again.";
    case "offline":
      return "You're offline. Your recording wasn't sent.";
    case "too_large":
      return "The recording is too long or too large. Try a shorter message.";
    case "provider_busy":
      return "The voice service is busy or has reached its limit. Please wait a moment and try again.";
    case "provider_unavailable":
      return "The voice service is temporarily unavailable. Try again later, or type your message.";
    case "not_allowed":
      return "Voice isn't available for you on this clone.";
    default:
      return "Something went wrong with the voice message.";
  }
}

export function formatSeconds(total: number): string {
  const safe = Math.max(0, Math.floor(total));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}
