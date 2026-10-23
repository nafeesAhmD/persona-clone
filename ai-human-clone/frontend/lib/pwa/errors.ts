/**
 * Classifies API / network failures into a small set of kinds the UI can act on
 * (Phase 15). Pure logic: no React, no DOM, so it is unit-tested with node --test.
 */

import { OFFLINE_MESSAGE } from "./network.ts";

export type ApiErrorKind =
  | "offline" // the device has no network (navigator.onLine === false)
  | "timeout" // the request took longer than the client timeout
  | "network" // online, but the API server could not be reached (DNS, CORS, refused)
  | "maintenance" // 503 with { maintenance: true }
  | "unavailable" // 502/503/504: server or an AI provider temporarily unavailable
  | "auth" // 401: session missing or expired
  | "forbidden" // 403
  | "not_found" // 404 / 410
  | "rate_limit" // 429: too many requests, try again shortly
  | "usage_limit" // 429: plan / monthly usage limit reached
  | "invalid" // 400 / 409 / 413 / 415 / 422: the request itself was rejected
  | "server"; // anything else (500, unexpected)

/** Kinds where trying the same (read) request again later can succeed. */
export const RETRYABLE_KINDS: ReadonlySet<ApiErrorKind> = new Set([
  "offline",
  "timeout",
  "network",
  "unavailable",
  "maintenance",
  "rate_limit",
  "server",
]);

/** Does a 429 message describe a plan/usage limit (vs. a short-term rate limit)? */
export function isUsageLimitMessage(message: string): boolean {
  const text = message.toLowerCase();
  if (text.includes("rate limit") || text.includes("too many")) return false;
  return text.includes("limit") || text.includes("quota");
}

export interface HttpFailure {
  status: number;
  message: string;
  /** The JSON body's `maintenance` flag (internal API sends it on maintenance 503s). */
  maintenance?: boolean;
  /** A structured `detail` object, e.g. a usage-limit payload with a `limit` field. */
  detail?: unknown;
}

/** Kind for an HTTP error response. */
export function classifyStatus({ status, message, maintenance, detail }: HttpFailure): ApiErrorKind {
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  if (status === 404 || status === 410) return "not_found";
  if (status === 429) {
    const structuredLimit = typeof detail === "object" && detail !== null && "limit" in detail;
    return structuredLimit || isUsageLimitMessage(message) ? "usage_limit" : "rate_limit";
  }
  if (status === 503 && maintenance) return "maintenance";
  if (status === 502 || status === 503 || status === 504) return "unavailable";
  if (status === 408) return "timeout";
  if (status >= 400 && status < 500) return "invalid";
  return "server";
}

/** Kind for a fetch that threw before any response arrived. */
export function classifyFetchFailure(input: { online: boolean; timedOut: boolean }): ApiErrorKind {
  if (input.timedOut) return "timeout";
  if (!input.online) return "offline";
  return "network";
}

/** Default user-facing message per kind (never stack traces or internals). */
export function defaultMessage(kind: ApiErrorKind): string {
  switch (kind) {
    case "offline":
      return OFFLINE_MESSAGE;
    case "timeout":
      return "The server took too long to respond. Please try again.";
    case "network":
      return "Could not reach the API server";
    case "maintenance":
      return "The app is under maintenance. Please try again later.";
    case "unavailable":
      return "The service is temporarily unavailable. Please try again shortly.";
    case "auth":
      return "Your session has ended. Please log in again.";
    case "forbidden":
      return "You don't have access to this.";
    case "not_found":
      return "This doesn't exist or is no longer available.";
    case "rate_limit":
      return "Too many requests. Please wait a moment and try again.";
    case "usage_limit":
      return "You have reached a usage limit.";
    case "invalid":
      return "The request could not be completed.";
    default:
      return "Something went wrong. Please try again.";
  }
}

/** Methods that may be retried automatically (never POST/PATCH/PUT/DELETE). */
export function isSafeMethod(method: string | undefined): boolean {
  const m = (method ?? "GET").toUpperCase();
  return m === "GET" || m === "HEAD";
}

/**
 * Should a failed request be retried automatically? Only idempotent reads (GET/HEAD),
 * at most once, and only for blips (connection failed while online, 502/504-style
 * unavailability). Timeouts, offline, maintenance and rate limits are never retried.
 */
export function shouldAutoRetry(method: string | undefined, kind: ApiErrorKind, attempt: number): boolean {
  if (!isSafeMethod(method) || attempt >= 1) return false;
  return kind === "network" || kind === "unavailable";
}
