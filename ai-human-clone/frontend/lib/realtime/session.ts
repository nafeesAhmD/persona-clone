/**
 * Live voice session state machine (pure: no React, no DOM), used by useRealtimeVoice.
 *
 *   idle ─start─▶ requesting_mic ─granted─▶ connecting ─ready─▶ connected ─end─▶ ending ─▶ ended
 *                       │ denied                │ failure            │ fatal error / lost
 *                       ▼                       ▼                    ▼
 *                     failed ◀──────────────────┴────────────────────┘
 *
 * While connected, `activity` follows the server (listening / thinking / speaking), and
 * the transcript collects what the user said and the clone's streamed answers. A new
 * session ("Try again") starts from ended/failed only: there is no automatic reconnect.
 */

import type { ConversationState, EndReason, RealtimeSpeechMode, ServerMessage } from "@/types/realtime";

export type SessionPhase = "idle" | "requesting_mic" | "connecting" | "connected" | "ending" | "ended" | "failed";

export interface TranscriptEntry {
  id: string;
  role: "you" | "clone";
  turn: number;
  text: string;
  /** The clone is still writing this answer. */
  streaming: boolean;
  interrupted: boolean;
}

export interface SessionError {
  code: string;
  message: string | null;
}

export interface RealtimeState {
  phase: SessionPhase;
  activity: ConversationState;
  muted: boolean;
  speechMode: RealtimeSpeechMode;
  sessionId: string | null;
  conversationId: string | null;
  maxDurationSeconds: number;
  /** Date.now() when connected. */
  connectedAt: number | null;
  transcript: TranscriptEntry[];
  /** A fatal error (phase failed) or a passing one shown as a banner (still connected). */
  error: SessionError | null;
  endReason: EndReason | null;
  /** Highest turn the user interrupted: its text and audio are dropped. */
  interruptedTurn: number;
}

export type RealtimeEvent =
  | { type: "start" }
  | { type: "mic_granted" }
  | { type: "session_created"; sessionId: string; conversationId: string | null; speechMode: RealtimeSpeechMode; maxDurationSeconds: number }
  | { type: "server"; message: ServerMessage; now: number }
  | { type: "user_text"; text: string; turn: number }
  | { type: "interrupt"; turn: number }
  | { type: "toggle_mute" }
  | { type: "set_speech_mode"; mode: RealtimeSpeechMode }
  | { type: "end_requested" }
  | { type: "closed"; errorCode: string | null }
  | { type: "fail"; code: string; message?: string | null }
  | { type: "dismiss_error" }
  | { type: "reset" };

export const INITIAL_REALTIME: RealtimeState = {
  phase: "idle",
  activity: "listening",
  muted: false,
  speechMode: "voice",
  sessionId: null,
  conversationId: null,
  maxDurationSeconds: 600,
  connectedAt: null,
  transcript: [],
  error: null,
  endReason: null,
  interruptedTurn: -1,
};

const isLive = (phase: SessionPhase) => phase === "connecting" || phase === "connected";

function upsertAnswer(
  transcript: TranscriptEntry[],
  turn: number,
  change: (entry: TranscriptEntry) => TranscriptEntry,
): TranscriptEntry[] {
  const index = transcript.findIndex((e) => e.role === "clone" && e.turn === turn);
  if (index < 0) {
    const fresh: TranscriptEntry = { id: `clone-${turn}`, role: "clone", turn, text: "", streaming: true, interrupted: false };
    return [...transcript, change(fresh)];
  }
  const next = transcript.slice();
  next[index] = change(transcript[index]);
  return next;
}

function onServer(state: RealtimeState, message: ServerMessage, now: number): RealtimeState {
  switch (message.type) {
    case "ready":
      return {
        ...state,
        phase: "connected",
        activity: "listening",
        sessionId: message.session_id,
        conversationId: message.conversation_id ?? state.conversationId,
        speechMode: message.speech_mode,
        maxDurationSeconds: message.max_duration_seconds,
        connectedAt: state.connectedAt ?? now,
        error: null,
      };
    case "state":
      return state.phase === "connected" ? { ...state, activity: message.state } : state;
    case "transcript":
      if (!message.text.trim()) return state;
      return {
        ...state,
        transcript: [
          // Replaces a typed message shown locally (the server may echo it as a transcript).
          ...state.transcript.filter(
            (e) => !(e.role === "you" && (e.turn === message.turn || (e.id.startsWith("local-") && e.text === message.text))),
          ),
          { id: `you-${message.turn}`, role: "you", turn: message.turn, text: message.text, streaming: false, interrupted: false },
        ],
      };
    case "answer_delta":
      if (message.turn <= state.interruptedTurn) return state;
      return { ...state, transcript: upsertAnswer(state.transcript, message.turn, (e) => ({ ...e, text: e.text + message.text })) };
    case "answer":
      return {
        ...state,
        transcript: upsertAnswer(state.transcript, message.turn, (e) => ({
          ...e,
          text: message.text || e.text,
          streaming: false,
          interrupted: e.interrupted || message.turn <= state.interruptedTurn,
        })),
      };
    case "turn_done":
      return {
        ...state,
        transcript: state.transcript.map((e) => (e.role === "clone" && e.turn === message.turn ? { ...e, streaming: false } : e)),
      };
    case "interrupted":
      return {
        ...state,
        interruptedTurn: Math.max(state.interruptedTurn, message.turn),
        transcript: state.transcript.map((e) =>
          e.role === "clone" && e.turn === message.turn ? { ...e, streaming: false, interrupted: true } : e,
        ),
      };
    case "error":
      if (message.fatal) return { ...state, phase: "failed", error: { code: message.code, message: message.message } };
      return { ...state, error: { code: message.code, message: message.message } };
    case "ended":
      return {
        ...state,
        phase: message.reason === "error" ? "failed" : "ended",
        endReason: message.reason,
        error: message.reason === "error" ? state.error ?? { code: "provider_unavailable", message: null } : state.error,
      };
    default:
      return state;
  }
}

export function realtimeReducer(state: RealtimeState, event: RealtimeEvent): RealtimeState {
  switch (event.type) {
    case "start":
      if (state.phase !== "idle" && state.phase !== "ended" && state.phase !== "failed") return state;
      return { ...INITIAL_REALTIME, phase: "requesting_mic", speechMode: state.speechMode };
    case "mic_granted":
      return state.phase === "requesting_mic" ? { ...state, phase: "connecting" } : state;
    case "session_created":
      if (state.phase !== "connecting") return state;
      return {
        ...state,
        sessionId: event.sessionId,
        conversationId: event.conversationId,
        speechMode: event.speechMode,
        maxDurationSeconds: event.maxDurationSeconds,
      };
    case "server":
      if (!isLive(state.phase) && state.phase !== "ending") return state;
      return onServer(state, event.message, event.now);
    case "user_text":
      if (state.phase !== "connected") return state;
      return {
        ...state,
        transcript: [
          ...state.transcript,
          { id: `local-${event.turn}`, role: "you", turn: event.turn, text: event.text, streaming: false, interrupted: false },
        ],
      };
    case "interrupt":
      if (state.phase !== "connected") return state;
      return {
        ...state,
        activity: "listening",
        interruptedTurn: Math.max(state.interruptedTurn, event.turn),
        transcript: state.transcript.map((e) =>
          e.role === "clone" && e.turn <= event.turn && e.streaming ? { ...e, streaming: false, interrupted: true } : e,
        ),
      };
    case "toggle_mute":
      return { ...state, muted: !state.muted };
    case "set_speech_mode":
      return { ...state, speechMode: event.mode };
    case "end_requested":
      return isLive(state.phase) ? { ...state, phase: "ending", endReason: "client" } : state;
    case "closed":
      if (state.phase === "ending") return { ...state, phase: "ended", endReason: state.endReason ?? "client" };
      if (!isLive(state.phase)) return state;
      if (!event.errorCode) return { ...state, phase: "ended", endReason: state.endReason ?? "client" };
      return { ...state, phase: "failed", error: { code: event.errorCode, message: null } };
    case "fail":
      if (state.phase === "ended" || state.phase === "idle") return state;
      return { ...state, phase: "failed", error: { code: event.code, message: event.message ?? null } };
    case "dismiss_error":
      return state.phase === "failed" ? state : { ...state, error: null };
    case "reset":
      return { ...INITIAL_REALTIME, speechMode: state.speechMode };
    default:
      return state;
  }
}

/** The highest turn seen so far (to interrupt "the current answer"). */
export function currentTurn(state: RealtimeState): number {
  return state.transcript.reduce((max, entry) => Math.max(max, entry.turn), -1);
}

export function elapsedSeconds(state: RealtimeState, now: number): number {
  return state.connectedAt === null ? 0 : Math.max(0, Math.floor((now - state.connectedAt) / 1000));
}

export function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Can a (new) session be started from here? */
export function canStart(state: RealtimeState): boolean {
  return state.phase === "idle" || state.phase === "ended" || state.phase === "failed";
}
