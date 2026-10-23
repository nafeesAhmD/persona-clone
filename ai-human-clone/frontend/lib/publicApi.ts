/**
 * Client for the public clone API (/api/public/...). No login and no cookies:
 * a visitor is identified only by their session token, sent in the
 * X-Public-Session header and kept in this browser's localStorage per clone.
 */

import { API_URL, ApiError, audioExtension } from "@/lib/api";
import type {
  PublicChatResponse,
  PublicClone,
  PublicCloneList,
  PublicJob,
  PublicSession,
} from "@/types/public";

const base = (slug: string) => `${API_URL}/api/public/clones/${encodeURIComponent(slug)}`;

async function call<T>(url: string, init: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("X-Public-Session", token);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers, credentials: "omit", cache: "no-store" });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const detail = ((await response.json()) as { detail?: unknown }).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail) && detail[0]?.msg) message = String(detail[0].msg);
    } catch {
      // Not JSON.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Session token (per clone, this browser only) ---

const tokenKey = (slug: string) => `ai-clone:public-session:${slug}`;

export function loadSessionToken(slug: string): string | null {
  try {
    return localStorage.getItem(tokenKey(slug));
  } catch {
    return null;
  }
}

export function saveSessionToken(slug: string, token: string | null): void {
  try {
    if (token) localStorage.setItem(tokenKey(slug), token);
    else localStorage.removeItem(tokenKey(slug));
  } catch {
    // Storage blocked: the conversation lasts for this page only.
  }
}

// --- Endpoints ---

export function getPublicClone(slug: string): Promise<PublicClone> {
  return call<PublicClone>(base(slug));
}

export function listPublicClones(params: Record<string, string | number | undefined>): Promise<PublicCloneList> {
  const query = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value !== undefined && value !== "")
      .map(([key, value]) => [key, String(value)]),
  ).toString();
  return call<PublicCloneList>(`${API_URL}/api/public/clones${query ? `?${query}` : ""}`);
}

export function sendPublicMessage(
  slug: string,
  message: string,
  token: string | null,
  inputMode: "text" | "voice" = "text",
): Promise<PublicChatResponse> {
  return call<PublicChatResponse>(
    `${base(slug)}/chat`,
    { method: "POST", body: JSON.stringify({ message, input_mode: inputMode }) },
    token,
  );
}

export function getPublicSession(slug: string, token: string): Promise<PublicSession> {
  return call<PublicSession>(`${base(slug)}/session`, {}, token);
}

export function endPublicSession(slug: string, token: string): Promise<void> {
  return call<void>(`${base(slug)}/session`, { method: "DELETE" }, token);
}

export function transcribePublic(slug: string, recording: Blob): Promise<{ text: string }> {
  const form = new FormData();
  form.append("audio", recording, `voice.${audioExtension(recording.type)}`);
  return call<{ text: string }>(`${base(slug)}/voice/transcribe`, { method: "POST", body: form });
}

export function speakPublicMessage(slug: string, token: string, messageId: string): Promise<{ audio_url: string }> {
  return call<{ audio_url: string }>(`${base(slug)}/messages/${encodeURIComponent(messageId)}/speech`, { method: "POST" }, token);
}

export function createPublicVideo(slug: string, token: string, messageId: string): Promise<{ job_id: string }> {
  return call<{ job_id: string }>(`${base(slug)}/messages/${encodeURIComponent(messageId)}/avatar`, { method: "POST" }, token);
}

export function getPublicJob(slug: string, token: string, jobId: string): Promise<PublicJob> {
  return call<PublicJob>(`${base(slug)}/avatar/jobs/${encodeURIComponent(jobId)}`, {}, token);
}

/** A protected file of this session (audio/video) as an object URL. */
export async function loadPublicMedia(path: string, token: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { headers: { "X-Public-Session": token }, credentials: "omit", cache: "no-store" });
  } catch {
    throw new ApiError("Could not reach the server.");
  }
  if (!response.ok) throw new ApiError("This file has expired or isn't available.", response.status);
  return URL.createObjectURL(await response.blob());
}

/** Absolute URL for an image the API serves publicly (or an owner-provided URL as is). */
export function publicImageUrl(url: string | null): string | null {
  if (!url) return null;
  return url.startsWith("/api/") ? `${API_URL}${url}` : url;
}
