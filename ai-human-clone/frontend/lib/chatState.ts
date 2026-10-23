/**
 * Pure helpers for the mobile chat (no React, no DOM), tested in tests/chatState.test.ts.
 */

export type FailureKind =
  | "offline"
  | "timeout"
  | "unavailable"
  | "auth"
  | "rate_limit"
  | "usage_limit"
  | "forbidden"
  | "not_found"
  | "invalid"
  | "server";

const KINDS: ReadonlySet<string> = new Set([
  "offline",
  "timeout",
  "unavailable",
  "auth",
  "rate_limit",
  "usage_limit",
  "forbidden",
  "not_found",
  "invalid",
  "server",
]);

/**
 * The kind of an API failure. Uses `error.kind` when lib/api's ApiError provides it,
 * otherwise derives it from the HTTP status (no status = the request never arrived).
 */
export function failureKind(error: unknown, online = true): FailureKind {
  const candidate = error as { kind?: unknown; status?: unknown } | null;
  if (candidate && typeof candidate.kind === "string") {
    if (KINDS.has(candidate.kind)) return candidate.kind as FailureKind;
    // lib/api also reports "network" (server unreachable) and "maintenance".
    if (candidate.kind === "network" || candidate.kind === "maintenance") return "unavailable";
  }
  const status = typeof candidate?.status === "number" ? candidate.status : undefined;
  if (status === undefined) return online ? "unavailable" : "offline";
  if (status === 401) return "auth";
  if (status === 402) return "usage_limit";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 408 || status === 504) return "timeout";
  if (status === 429) return "rate_limit";
  if (status === 502 || status === 503) return "unavailable";
  if (status >= 500) return "server";
  return "invalid";
}

/** A short, friendly reason for a message that couldn't be sent. */
export function sendFailureMessage(kind: FailureKind, serverMessage?: string): string {
  switch (kind) {
    case "offline":
      return "You're offline. Your message wasn't sent.";
    case "timeout":
      return "The clone took too long to answer.";
    case "unavailable":
      return "The clone can't be reached right now.";
    case "auth":
      return "Your session has ended. Please log in again.";
    case "rate_limit":
      return "Too many messages at once. Wait a moment, then try again.";
    case "usage_limit":
      return serverMessage || "The usage limit has been reached.";
    case "forbidden":
      return serverMessage || "You can't chat with this clone.";
    case "not_found":
      return "This clone or conversation no longer exists.";
    case "invalid":
      return serverMessage || "The message couldn't be sent.";
    default:
      return serverMessage || "Something went wrong while answering.";
  }
}

/** Whether "Retry" makes sense (it only ever re-sends when the user taps it). */
export function isRetryable(kind: FailureKind): boolean {
  return kind !== "auth" && kind !== "forbidden" && kind !== "not_found" && kind !== "usage_limit";
}

/** True when the reader is at (or close to) the newest message: only then follow new content. */
export function isNearBottom(
  metrics: { scrollTop: number; scrollHeight: number; clientHeight: number },
  threshold = 120,
): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold;
}

/**
 * Height for a full-screen panel that starts `top` px below the top of the layout
 * viewport. `visualHeight` is window.visualViewport.height when available: on iOS the
 * keyboard shrinks only the visual viewport, so using it keeps the composer above it.
 */
export function fillHeight(layoutHeight: number, visualHeight: number | null, top: number): number {
  const visible = visualHeight && visualHeight > 0 ? Math.min(layoutHeight, visualHeight) : layoutHeight;
  return Math.max(240, Math.round(visible - Math.max(0, top)));
}
