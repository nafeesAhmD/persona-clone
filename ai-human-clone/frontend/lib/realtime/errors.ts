/**
 * Real-time voice errors → friendly messages (pure). Codes from the server
 * (docs/phase17/contract.md) plus the browser's own (microphone, support, network).
 */

export type LocalErrorCode =
  | "mic_denied"
  | "mic_missing"
  | "mic_busy"
  | "unsupported"
  | "connection_lost"
  | "network";

const MESSAGES: Record<string, string> = {
  realtime_disabled: "Live voice is turned off on this server.",
  provider_not_configured: "Live voice isn't set up on this server yet (no speech provider is configured).",
  consent_missing: "Voice is off for this clone, or the owner hasn't given voice consent.",
  realtime_off: "The owner has turned live voice off for this clone.",
  forbidden: "You don't have access to talk to this clone.",
  rate_limited: "Too many live voice sessions were started. Wait a minute and try again.",
  too_many_sessions: "A live voice session is already open (maybe in another tab). End it first, then try again.",
  quota_exceeded: "Your plan's live voice limit for this month is used up.",
  session_not_found: "This live voice session no longer exists. Start a new one.",
  session_expired: "The live voice session expired. Start a new one.",
  provider_unavailable: "The voice service is busy or unavailable right now. Please try again.",
  signaling_failed: "Couldn't connect the live voice session. Please try again.",
  mic_denied: "Microphone access was blocked. Allow the microphone in your browser's site settings, then try again.",
  mic_missing: "No microphone was found. Connect one and try again.",
  mic_busy: "The microphone is being used by another app. Close it and try again.",
  unsupported: "This browser can't do live voice (it needs microphone recording and WebSockets). Try a recent Chrome, Edge, Firefox or Safari.",
  connection_lost: "The connection was lost. Start a new session to continue.",
  network: "Couldn't reach the server. Check your connection and try again.",
};

export function realtimeErrorMessage(code: string | null | undefined, fallback?: string): string {
  if (code && MESSAGES[code]) return MESSAGES[code];
  return fallback || "Something went wrong with live voice. Please try again.";
}

/** Error codes for which "try again" can work without changing anything. */
export function isRetryable(code: string | null | undefined): boolean {
  return !code || ["provider_unavailable", "signaling_failed", "connection_lost", "network", "session_expired", "session_not_found", "rate_limited"].includes(code);
}

/** The contract code from an HTTP error body ({code, detail} or {detail: {code, message}}) and status. */
export function errorFromBody(status: number, body: unknown): { code: string; message: string } {
  let code: string | null = null;
  let message: string | null = null;
  if (body && typeof body === "object") {
    const data = body as Record<string, unknown>;
    if (typeof data.code === "string") code = data.code;
    const detail = data.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object") {
      const inner = detail as Record<string, unknown>;
      if (!code && typeof inner.code === "string") code = inner.code;
      if (typeof inner.message === "string") message = inner.message;
    }
    if (!message && typeof data.message === "string") message = data.message;
  }
  if (!code) {
    code =
      status === 401 || status === 403 || status === 404
        ? status === 404 ? "session_not_found" : "forbidden"
        : status === 410 ? "session_expired"
        : status === 429 ? "rate_limited"
        : status === 402 ? "quota_exceeded"
        : "provider_unavailable";
  }
  return { code, message: message || realtimeErrorMessage(code) };
}

/** A WebSocket close code (contract: 4403/4404/4410/4400) → error code, or null for a normal close. */
export function closeCodeError(code: number): string | null {
  switch (code) {
    case 1000:
      return null;
    case 4403:
      return "forbidden";
    case 4404:
      return "session_not_found";
    case 4410:
      return "session_expired";
    case 4400:
      return "signaling_failed";
    case 1013: // server in maintenance mode: try again later
      return "provider_unavailable";
    default:
      return "connection_lost";
  }
}

/** getUserMedia failures → local codes. */
export function micErrorCode(error: unknown): LocalErrorCode {
  const name = error && typeof error === "object" && "name" in error ? String((error as { name: unknown }).name) : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "mic_denied";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return "mic_missing";
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") return "mic_busy";
  return "mic_denied";
}
