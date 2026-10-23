/**
 * Real-time voice API (Phase 17, docs/phase17/contract.md). Logged-in calls send the
 * session cookie; public visitors send their public chat token (X-Public-Session).
 * Errors keep the contract's `code` so the UI can explain each case.
 */

import { API_URL } from "@/lib/api";
import { buildWsUrl } from "@/lib/realtime/protocol";
import { errorFromBody } from "@/lib/realtime/errors";
import type {
  RealtimeSessionCreated,
  RealtimeSessionInfo,
  RealtimeSettings,
  RealtimeSettingsUpdate,
} from "@/types/realtime";

export class RealtimeApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "RealtimeApiError";
  }
}

interface CallOptions {
  method?: string;
  body?: unknown;
  publicToken?: string | null;
  keepalive?: boolean;
}

async function call<T>(path: string, { method = "GET", body, publicToken, keepalive }: CallOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (publicToken) headers["X-Public-Session"] = publicToken;
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      // Public visitors have no login: never send cookies for them.
      credentials: publicToken ? "omit" : "include",
      cache: "no-store",
      keepalive,
    });
  } catch {
    throw new RealtimeApiError("Couldn't reach the server.", "network");
  }
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      // Not JSON (e.g. a proxy page).
    }
    const { code, message } = errorFromBody(response.status, parsed);
    throw new RealtimeApiError(message, code, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const clonePath = (cloneId: string) => `/api/clones/${encodeURIComponent(cloneId)}/realtime`;
const publicPath = (slug: string) => `/api/public/clones/${encodeURIComponent(slug)}/realtime`;

// --- Owner settings ---

export function getRealtimeSettings(cloneId: string): Promise<RealtimeSettings> {
  return call<RealtimeSettings>(`${clonePath(cloneId)}/settings`);
}

export function updateRealtimeSettings(cloneId: string, update: RealtimeSettingsUpdate): Promise<RealtimeSettings> {
  return call<RealtimeSettings>(`${clonePath(cloneId)}/settings`, { method: "PATCH", body: update });
}

// --- Sessions: a logged-in user, or a public visitor ---

export type RealtimeTarget =
  | { kind: "clone"; cloneId: string; conversationId?: string | null }
  | { kind: "public"; slug: string; token: string };

export function createRealtimeSession(target: RealtimeTarget): Promise<RealtimeSessionCreated> {
  if (target.kind === "public") {
    return call<RealtimeSessionCreated>(`${publicPath(target.slug)}/session`, { method: "POST", body: {}, publicToken: target.token });
  }
  return call<RealtimeSessionCreated>(`${clonePath(target.cloneId)}/session`, {
    method: "POST",
    body: { conversation_id: target.conversationId ?? null },
  });
}

export function getRealtimeSession(cloneId: string, sessionId: string): Promise<RealtimeSessionInfo> {
  return call<RealtimeSessionInfo>(`${clonePath(cloneId)}/session/${encodeURIComponent(sessionId)}`);
}

/** Ends the session (idempotent). `keepalive` lets it finish while the tab closes. */
export function endRealtimeSession(target: RealtimeTarget, sessionId: string, keepalive = false): Promise<RealtimeSessionInfo | undefined> {
  const id = encodeURIComponent(sessionId);
  if (target.kind === "public") {
    return call(`${publicPath(target.slug)}/session/${id}/end`, { method: "POST", publicToken: target.token, keepalive });
  }
  return call(`${clonePath(target.cloneId)}/session/${id}/end`, { method: "POST", keepalive });
}

export function realtimeSocketUrl(session: Pick<RealtimeSessionCreated, "ws_path" | "ticket">): string {
  return buildWsUrl(API_URL, session.ws_path, session.ticket);
}
