/** Phase 17 real-time voice: see docs/phase17/contract.md (the source of truth). */

export type RealtimeSpeechMode = "voice" | "browser";

export type RealtimeUnavailableReason = "disabled" | "provider_not_configured" | "voice_off" | "consent_missing";

export interface RealtimeCapabilities {
  transport: string;
  interruption: boolean;
  streaming_text: boolean;
  /** A text-to-speech provider is configured on the server. */
  server_speech: boolean;
  /** This clone speaks with its cloned voice. */
  cloned_voice: boolean;
  languages: string[];
}

export interface RealtimeLimits {
  max_duration_seconds: number;
  session_ttl_seconds: number;
  max_utterance_seconds: number;
  max_utterance_bytes: number;
}

/** GET /api/clones/{id}/realtime/settings (owner only). */
export interface RealtimeSettings {
  available: boolean;
  reason: RealtimeUnavailableReason | null;
  provider: string | null;
  enabled: boolean;
  public_enabled: boolean;
  speech_mode: RealtimeSpeechMode;
  capabilities: RealtimeCapabilities;
  limits: RealtimeLimits;
}

export interface RealtimeSettingsUpdate {
  enabled?: boolean;
  public_enabled?: boolean;
  speech_mode?: RealtimeSpeechMode;
}

export interface RealtimeSessionCreated {
  session_id: string;
  status: RealtimeSessionStatus;
  provider: string;
  conversation_id: string | null;
  ws_path: string;
  /** One-time, short-lived; only ever put in the WebSocket URL. */
  ticket: string;
  ticket_expires_at: string;
  expires_at: string;
  max_duration_seconds: number;
  speech_mode: RealtimeSpeechMode;
  capabilities: RealtimeCapabilities;
}

export type RealtimeSessionStatus = "created" | "connecting" | "connected" | "ended" | "failed" | "expired";

export interface RealtimeSessionInfo {
  session_id: string;
  status: RealtimeSessionStatus;
  provider: string;
  conversation_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  error_code: string | null;
  expires_at: string | null;
}

export type RealtimeErrorCode =
  | "realtime_disabled"
  | "provider_not_configured"
  | "consent_missing"
  | "realtime_off"
  | "forbidden"
  | "rate_limited"
  | "too_many_sessions"
  | "quota_exceeded"
  | "session_not_found"
  | "session_expired"
  | "provider_unavailable"
  | "signaling_failed";

export type ConversationState = "listening" | "thinking" | "speaking";

export type EndReason = "client" | "max_duration" | "expired" | "error";

// --- Server → client (text frames; an "audio" header is followed by one binary frame) ---

export type ServerMessage =
  | { type: "ready"; session_id: string; conversation_id: string | null; speech_mode: RealtimeSpeechMode; max_duration_seconds: number }
  | { type: "state"; state: ConversationState }
  | { type: "transcript"; turn: number; text: string; language: string | null }
  | { type: "answer_delta"; turn: number; text: string }
  | { type: "answer"; turn: number; text: string; message_id: string | null }
  | { type: "audio"; turn: number; seq: number; mime: string }
  | { type: "turn_done"; turn: number }
  | { type: "interrupted"; turn: number }
  | { type: "error"; code: string; message: string; turn?: number; fatal: boolean }
  | { type: "ended"; reason: EndReason }
  | { type: "pong" };

// --- Client → server (text frames; a user utterance is sent as one binary frame) ---

export type ClientMessage =
  | { type: "hello" }
  | { type: "text"; text: string }
  | { type: "interrupt" }
  | { type: "speech_mode"; mode: RealtimeSpeechMode }
  | { type: "end" }
  | { type: "ping" };
