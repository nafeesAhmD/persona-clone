import type {
  ChatMessage,
  ChatSource,
  CloneChatProfile,
  CloneCreatePayload,
  CloneProfile,
  CloneSummary,
  CloneUpdatePayload,
  Conversation,
  ConversationListItem,
  DocumentDetail,
  DocumentListItem,
  HealthResponse,
  IndexResult,
  KnowledgeSearchResponse,
  ManualKnowledgePayload,
  SendMessageRequest,
  SendMessageResponse,
} from "@/types/clone";
import type { LoginInput, PasswordChange, ProfileUpdate, RegisterInput, User } from "@/types/auth";
import type { AvatarJob, AvatarSettings, AvatarSettingsUpdate, AvatarStyle, CloneAvatar } from "@/types/avatar";
import type {
  CloneMemory,
  MemoryCreatePayload,
  MemoryExtractionResult,
  MemoryStatus,
  MemoryType,
  MemoryUpdatePayload,
} from "@/types/memory";
import type { Transcription, VoiceChatResponse, VoiceSettings, VoiceSettingsUpdate } from "@/types/voice";
import type { ContentVisibility, PublicSettings, PublicSettingsUpdate } from "@/types/public";

import { beginBusy } from "@/lib/busy";
import {
  type ApiErrorKind,
  classifyFetchFailure,
  classifyStatus,
  defaultMessage,
  shouldAutoRetry,
} from "@/lib/pwa/errors";

export type { ApiErrorKind } from "@/lib/pwa/errors";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Default time limit for apiFetch requests (file uploads have none; streams have their own). */
export const DEFAULT_TIMEOUT_MS = 30_000;
/** Speech can take minutes: a self-hosted cloned voice is generated on the CPU. */
export const SPEECH_TIMEOUT_MS = 600_000;

/**
 * Window event fired when an API call returns 401 (session missing or expired),
 * except for /api/auth/* calls (login with a wrong password, the initial /me check).
 * `event.detail` is `{ path: string }`. AuthProvider / RequireAuth can listen and
 * clear the user + redirect to /login.
 */
export const AUTH_EXPIRED_EVENT = "ahc:auth-expired";

function browserOnline(): boolean {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

/**
 * Every API failure. `kind` tells the UI what happened (see lib/pwa/errors.ts):
 * "offline" | "timeout" | "network" | "maintenance" | "unavailable" | "auth" |
 * "forbidden" | "not_found" | "rate_limit" | "usage_limit" | "invalid" | "server".
 * `message` is always user-safe (the API's `detail`, never a stack trace).
 */
export class ApiError extends Error {
  public readonly kind: ApiErrorKind;

  constructor(
    message: string,
    public readonly status?: number,
    kind?: ApiErrorKind,
  ) {
    super(message);
    this.name = "ApiError";
    this.kind =
      kind ??
      (status !== undefined
        ? classifyStatus({ status, message })
        : classifyFetchFailure({ online: browserOnline(), timedOut: false }));
  }
}

type ValidationDetail = { loc?: unknown[]; msg?: string };

function describeError(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{ loc: ["body", "name"], msg: "..." }]
  if (Array.isArray(detail) && detail.length > 0) {
    return (detail as ValidationDetail[])
      .map((d) => {
        const field = d.loc?.filter((part) => part !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  // Structured details, e.g. a usage limit: { message, limit, used, reset_at }.
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  return fallback;
}

/** Turns a non-OK response into an ApiError (reads the {"detail": ...} body if any). */
async function errorFromResponse(response: Response, path: string): Promise<ApiError> {
  let message = response.statusText || `Request failed (${response.status})`;
  let detail: unknown;
  let maintenance = false;
  try {
    const body = (await response.json()) as { detail?: unknown; maintenance?: unknown };
    detail = body.detail;
    maintenance = body.maintenance === true;
    message = describeError(detail, message);
  } catch {
    // Non-JSON error body (e.g. a proxy's 502 page); keep the status text.
  }
  const kind = classifyStatus({ status: response.status, message, maintenance, detail });
  // Gateways' HTML error pages have useless messages; say what happened instead.
  if ((kind === "unavailable" || kind === "server") && !detail) message = defaultMessage(kind);
  if (kind === "auth") notifyAuthExpired(path);
  return new ApiError(message, response.status, kind);
}

function notifyAuthExpired(path: string) {
  if (typeof window === "undefined" || path.startsWith("/api/auth/")) return;
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { path } }));
}

/** The ApiError for a fetch that threw (no response). Caller aborts are re-thrown as-is. */
function fetchFailure(error: unknown, timedOut: boolean, callerSignal?: AbortSignal | null): unknown {
  if (callerSignal?.aborted && !timedOut) return error;
  const kind = classifyFetchFailure({ online: browserOnline(), timedOut });
  return new ApiError(defaultMessage(kind), undefined, kind);
}

export interface ApiFetchOptions {
  /** Abort after this many ms (default 30s; 0 = no limit). FormData uploads default to no limit. */
  timeoutMs?: number;
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function apiFetch<T>(path: string, init?: RequestInit, options: ApiFetchOptions = {}): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method === "GET" || method === "HEAD") return sendRequest<T>(path, init, options);
  // A change is being saved: an app update waits until it's done (lib/busy.ts).
  const done = beginBusy();
  try {
    return await sendRequest<T>(path, init, options);
  } finally {
    done();
  }
}

async function sendRequest<T>(path: string, init: RequestInit | undefined, options: ApiFetchOptions): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const timeoutMs = options.timeoutMs ?? (isFormData ? 0 : DEFAULT_TIMEOUT_MS);

  for (let attempt = 0; ; attempt += 1) {
    const controller = new AbortController();
    let timedOut = false;
    const timer = timeoutMs > 0 ? setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs) : undefined;
    const callerSignal = init?.signal;
    const onCallerAbort = () => controller.abort();
    if (callerSignal?.aborted) controller.abort();
    else callerSignal?.addEventListener("abort", onCallerAbort, { once: true });

    let error: unknown;
    try {
      const response = await fetch(`${API_URL}${path}`, {
        ...init,
        signal: controller.signal,
        // Send the HttpOnly session cookie. JavaScript never reads it.
        credentials: "include",
        // Let the browser set the multipart boundary for file uploads.
        headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
      });
      if (response.ok) {
        if (response.status === 204) return undefined as T;
        return (await response.json()) as T;
      }
      error = await errorFromResponse(response, path);
    } catch (thrown) {
      error = thrown instanceof ApiError ? thrown : fetchFailure(thrown, timedOut, callerSignal);
    } finally {
      clearTimeout(timer);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    }

    // Only idempotent reads are retried, once, after a short pause. Never POST/PATCH/DELETE.
    if (error instanceof ApiError && shouldAutoRetry(init?.method, error.kind, attempt) && !callerSignal?.aborted) {
      await wait(800);
      continue;
    }
    throw error;
  }
}

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/health", { cache: "no-store" });
}

export interface LlmStatus {
  provider: string;
  configured: boolean;
  reachable: boolean;
  model: string;
}

export function getLlmStatus(): Promise<LlmStatus> {
  return apiFetch<LlmStatus>("/api/health/llm", { cache: "no-store" });
}

// --- Clones: management endpoints are owner-only; the API enforces it ---

const clonePath = (id: string) => `/api/clones/${encodeURIComponent(id)}`;

export function createClone(payload: CloneCreatePayload): Promise<CloneProfile> {
  return apiFetch<CloneProfile>("/api/clones", { method: "POST", body: JSON.stringify(payload) });
}

/** The logged-in user's clones. */
export function getMyClones(): Promise<CloneSummary[]> {
  return apiFetch<CloneSummary[]>("/api/clones", { cache: "no-store" });
}

/** Full settings of a clone you own. */
export function getClone(id: string): Promise<CloneProfile> {
  return apiFetch<CloneProfile>(clonePath(id), { cache: "no-store" });
}

export function updateClone(id: string, payload: CloneUpdatePayload): Promise<CloneProfile> {
  return apiFetch<CloneProfile>(clonePath(id), { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteClone(id: string): Promise<void> {
  return apiFetch<void>(clonePath(id), { method: "DELETE" });
}

/** Public, active clones anyone can chat with. */
export function listPublicClones(): Promise<CloneSummary[]> {
  return apiFetch<CloneSummary[]>("/api/clones/public", { cache: "no-store" });
}

/** Clone info for the chat screen, if the viewer is allowed to chat with it. */
export function getChatProfile(id: string): Promise<CloneChatProfile> {
  return apiFetch<CloneChatProfile>(`${clonePath(id)}/chat-profile`, { cache: "no-store" });
}

// --- Knowledge (owner only) ---

const documentsPath = (cloneId: string) => `${clonePath(cloneId)}/documents`;
const documentPath = (cloneId: string, documentId: string) =>
  `${documentsPath(cloneId)}/${encodeURIComponent(documentId)}`;

export function getCloneDocuments(cloneId: string): Promise<DocumentListItem[]> {
  return apiFetch<DocumentListItem[]>(documentsPath(cloneId), { cache: "no-store" });
}

export function getDocument(cloneId: string, documentId: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(documentPath(cloneId, documentId), { cache: "no-store" });
}

export function addManualKnowledge(cloneId: string, payload: ManualKnowledgePayload): Promise<DocumentListItem> {
  return apiFetch<DocumentListItem>(`${clonePath(cloneId)}/knowledge`, { method: "POST", body: JSON.stringify(payload) });
}

export function deleteDocument(cloneId: string, documentId: string): Promise<void> {
  return apiFetch<void>(documentPath(cloneId, documentId), { method: "DELETE" });
}

export function retryDocument(cloneId: string, documentId: string): Promise<DocumentListItem> {
  return apiFetch<DocumentListItem>(`${documentPath(cloneId, documentId)}/retry`, { method: "POST" });
}

// --- AI memory (vector index) ---

export function indexDocument(cloneId: string, documentId: string): Promise<IndexResult> {
  return apiFetch<IndexResult>(`${documentPath(cloneId, documentId)}/index`, { method: "POST" });
}

export function reindexDocument(cloneId: string, documentId: string): Promise<IndexResult> {
  return apiFetch<IndexResult>(`${documentPath(cloneId, documentId)}/reindex`, { method: "POST" });
}

/** Semantic search in a clone's memory. Returns matching chunks, not an AI answer. */
export function searchKnowledge(cloneId: string, query: string, topK = 5): Promise<KnowledgeSearchResponse> {
  return apiFetch<KnowledgeSearchResponse>(`${clonePath(cloneId)}/knowledge/search`, {
    method: "POST",
    body: JSON.stringify({ query, top_k: topK }),
  });
}

/**
 * Upload a knowledge file. Uses XMLHttpRequest because fetch can't report upload
 * progress; it sends the same session cookie (withCredentials) as apiFetch.
 */
export function uploadDocument(
  cloneId: string,
  file: File,
  options: { title?: string; onProgress?: (fraction: number) => void } = {},
): Promise<DocumentListItem> {
  const done = beginBusy();
  return sendDocument(cloneId, file, options).finally(done);
}

function sendDocument(
  cloneId: string,
  file: File,
  options: { title?: string; onProgress?: (fraction: number) => void },
): Promise<DocumentListItem> {
  const body = new FormData();
  body.append("file", file);
  if (options.title?.trim()) body.append("title", options.title.trim());

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}${documentsPath(cloneId)}`);
    request.withCredentials = true;
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as DocumentListItem);
      } else {
        const body = request.response as { detail?: unknown; maintenance?: unknown } | null;
        const message = describeError(body?.detail, `Upload failed (${request.status})`);
        const kind = classifyStatus({ status: request.status, message, maintenance: body?.maintenance === true, detail: body?.detail });
        if (kind === "auth") notifyAuthExpired(documentsPath(cloneId));
        reject(new ApiError(message, request.status, kind));
      }
    };
    request.onerror = () => {
      const kind = classifyFetchFailure({ online: browserOnline(), timedOut: false });
      reject(new ApiError(defaultMessage(kind), undefined, kind));
    };
    request.send(body);
  });
}

// --- Clone chat (login required; the API checks access to the clone) ---

/** One complete answer (non-streaming). `conversationId: null` starts a new conversation. */
export function sendCloneMessage(
  cloneId: string,
  message: string,
  conversationId: string | null,
): Promise<SendMessageResponse> {
  const body: SendMessageRequest = { message, conversation_id: conversationId };
  return apiFetch<SendMessageResponse>(`${clonePath(cloneId)}/chat`, { method: "POST", body: JSON.stringify(body) });
}

/** The current user's conversations with a clone, most recent first. */
export function getConversations(cloneId: string): Promise<ConversationListItem[]> {
  return apiFetch<ConversationListItem[]>(`${clonePath(cloneId)}/conversations`, { cache: "no-store" });
}

export function getConversation(conversationId: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/conversations/${encodeURIComponent(conversationId)}`, { cache: "no-store" });
}

export function deleteConversation(conversationId: string): Promise<void> {
  return apiFetch<void>(`/api/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}

export interface ChatStreamHandlers {
  onMeta?: (meta: { conversation_id: string; sources: ChatSource[]; memories_used?: number }) => void;
  onDelta: (text: string) => void;
}

/**
 * Streams a reply from POST /chat/stream (server-sent events) and resolves with the
 * saved assistant message. EventSource can't POST, so the stream is read manually.
 */
export async function streamCloneMessage(
  cloneId: string,
  message: string,
  conversationId: string | null,
  handlers: ChatStreamHandlers,
  inputMode: "text" | "voice" = "text",
): Promise<ChatMessage> {
  const done = beginBusy();
  try {
    return await streamAnswer(cloneId, message, conversationId, handlers, inputMode);
  } finally {
    done();
  }
}

async function streamAnswer(
  cloneId: string,
  message: string,
  conversationId: string | null,
  handlers: ChatStreamHandlers,
  inputMode: "text" | "voice",
): Promise<ChatMessage> {
  const path = `/api/clones/${encodeURIComponent(cloneId)}/chat/stream`;
  let response: Response;
  try {
    // No client timeout: answers stream for as long as the model writes. Never retried (POST).
    response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, conversation_id: conversationId, input_mode: inputMode }),
    });
  } catch (error) {
    throw fetchFailure(error, false);
  }

  if (!response.ok) throw await errorFromResponse(response, path);
  if (!response.body) throw new ApiError("The reply could not be read", response.status, "server");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<string>;
    try {
      chunk = await reader.read();
    } catch {
      // The connection dropped mid-answer (e.g. the phone lost signal).
      throw new ApiError("The connection closed before the reply finished", undefined, browserOnline() ? "network" : "offline");
    }
    const { value, done } = chunk;
    if (done) break;
    buffer += value;

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      const payload = JSON.parse(data);

      if (event === "meta") handlers.onMeta?.(payload);
      else if (event === "delta") handlers.onDelta(payload.text);
      else if (event === "error") throw new ApiError(payload.detail ?? "The clone could not answer", undefined, "server");
      else if (event === "done") return payload.message as ChatMessage;
    }
  }
  throw new ApiError("The connection closed before the reply finished", undefined, browserOnline() ? "network" : "offline");
}

// --- Long-term memory (owner only; the API checks clone and memory ownership) ---

const memoriesPath = (cloneId: string) => `${clonePath(cloneId)}/memories`;
const memoryPath = (cloneId: string, memoryId: string) => `${memoriesPath(cloneId)}/${encodeURIComponent(memoryId)}`;

export function getMemories(
  cloneId: string,
  filters: { status?: MemoryStatus; memory_type?: MemoryType } = {},
): Promise<CloneMemory[]> {
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value) as [string, string][]).toString();
  const suffix = query ? `?${query}` : "";
  return apiFetch<CloneMemory[]>(`${memoriesPath(cloneId)}${suffix}`, { cache: "no-store" });
}

/** A memory you write yourself is approved right away. */
export function createMemory(cloneId: string, payload: MemoryCreatePayload): Promise<CloneMemory> {
  return apiFetch<CloneMemory>(memoriesPath(cloneId), { method: "POST", body: JSON.stringify(payload) });
}

export function updateMemory(cloneId: string, memoryId: string, payload: MemoryUpdatePayload): Promise<CloneMemory> {
  return apiFetch<CloneMemory>(memoryPath(cloneId, memoryId), { method: "PATCH", body: JSON.stringify(payload) });
}

export function approveMemory(cloneId: string, memoryId: string): Promise<CloneMemory> {
  return apiFetch<CloneMemory>(`${memoryPath(cloneId, memoryId)}/approve`, { method: "POST" });
}

export function rejectMemory(cloneId: string, memoryId: string): Promise<CloneMemory> {
  return apiFetch<CloneMemory>(`${memoryPath(cloneId, memoryId)}/reject`, { method: "POST" });
}

export function deleteMemory(cloneId: string, memoryId: string): Promise<void> {
  return apiFetch<void>(memoryPath(cloneId, memoryId), { method: "DELETE" });
}

/** Deletes every memory of the clone. Call only after the user confirmed. */
export function clearMemories(cloneId: string): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>(`${memoriesPath(cloneId)}/clear`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  });
}

/** AI suggestions from a conversation, saved as candidates for review (never approved). */
export function extractMemories(conversationId: string): Promise<MemoryExtractionResult> {
  return apiFetch<MemoryExtractionResult>(
    `/api/conversations/${encodeURIComponent(conversationId)}/extract-memories`,
    { method: "POST" },
  );
}

// --- Voice (the API checks clone access, voice on/consent, and audio ownership) ---

const voicePath = (cloneId: string) => `${clonePath(cloneId)}/voice`;

export function getVoiceSettings(cloneId: string): Promise<VoiceSettings> {
  return apiFetch<VoiceSettings>(`${voicePath(cloneId)}/settings`, { cache: "no-store" });
}

export function updateVoiceSettings(cloneId: string, update: VoiceSettingsUpdate): Promise<VoiceSettings> {
  return apiFetch<VoiceSettings>(`${voicePath(cloneId)}/settings`, { method: "PATCH", body: JSON.stringify(update) });
}

export function testVoice(cloneId: string, text: string): Promise<{ audio_url: string }> {
  return apiFetch<{ audio_url: string }>(
    `${voicePath(cloneId)}/test`,
    { method: "POST", body: JSON.stringify({ text }) },
    { timeoutMs: SPEECH_TIMEOUT_MS },
  );
}

/** File extension the API expects for a recording's MIME type. */
export function audioExtension(mimeType: string): string {
  const type = mimeType.split(";")[0].trim();
  if (type === "audio/ogg") return "ogg";
  if (type === "audio/mp4" || type === "audio/aac") return "m4a";
  if (type === "audio/mpeg") return "mp3";
  if (type === "audio/wav") return "wav";
  return "webm";
}

function audioForm(recording: Blob, extra: Record<string, string | null> = {}): FormData {
  const form = new FormData();
  form.append("audio", recording, `voice.${audioExtension(recording.type)}`);
  for (const [key, value] of Object.entries(extra)) if (value) form.append(key, value);
  return form;
}

/** Speech to text, in the language spoken. */
export function transcribeVoice(cloneId: string, recording: Blob): Promise<Transcription> {
  return apiFetch<Transcription>(`${voicePath(cloneId)}/transcribe`, { method: "POST", body: audioForm(recording) });
}

/** One-shot voice turn: transcription, answer and spoken answer in a single request. */
export function sendVoiceMessage(cloneId: string, recording: Blob, conversationId: string | null): Promise<VoiceChatResponse> {
  return apiFetch<VoiceChatResponse>(`${voicePath(cloneId)}/chat`, {
    method: "POST",
    body: audioForm(recording, { conversation_id: conversationId }),
  });
}

/** Speech for a saved answer in your own conversation. */
export function speakMessage(conversationId: string, messageId: string): Promise<{ audio_url: string }> {
  return apiFetch<{ audio_url: string }>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/speech`,
    { method: "POST" },
    { timeoutMs: SPEECH_TIMEOUT_MS },
  );
}

/** Downloads a protected file (sent with the session cookie) as a playable/displayable object URL. */
export async function loadMedia(url: string, missing = "This file has expired or isn't available."): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${url}`, { credentials: "include" });
  } catch (error) {
    throw fetchFailure(error, false);
  }
  if (!response.ok) {
    const kind = classifyStatus({ status: response.status, message: missing });
    if (kind === "auth") notifyAuthExpired(url);
    // Expired / missing / forbidden files keep the friendly "missing" text.
    const message = kind === "not_found" || kind === "forbidden" || kind === "invalid" ? missing : defaultMessage(kind);
    throw new ApiError(message, response.status, kind);
  }
  return URL.createObjectURL(await response.blob());
}

/** Downloads generated audio as a playable object URL. */
export function loadAudio(audioUrl: string): Promise<string> {
  return loadMedia(audioUrl, "The voice response has expired or isn't available.");
}

// --- Avatar (owner only; the API checks clone, avatar and job ownership) ---

const avatarPath = (cloneId: string) => `${clonePath(cloneId)}/avatar`;

export function getAvatarSettings(cloneId: string): Promise<AvatarSettings> {
  return apiFetch<AvatarSettings>(avatarPath(cloneId), { cache: "no-store" });
}

export function updateAvatarSettings(cloneId: string, update: AvatarSettingsUpdate): Promise<AvatarSettings> {
  return apiFetch<AvatarSettings>(avatarPath(cloneId), { method: "PATCH", body: JSON.stringify(update) });
}

export function uploadAvatar(cloneId: string, image: File): Promise<CloneAvatar> {
  const form = new FormData();
  form.append("image", image);
  return apiFetch<CloneAvatar>(avatarPath(cloneId), { method: "POST", body: form });
}

export function generateAvatar(cloneId: string, choice: { preset: string } | { style: AvatarStyle }): Promise<CloneAvatar> {
  return apiFetch<CloneAvatar>(`${avatarPath(cloneId)}/generate`, { method: "POST", body: JSON.stringify(choice) });
}

export function deleteAvatar(cloneId: string, avatarId: string): Promise<void> {
  return apiFetch<void>(`${avatarPath(cloneId)}/${encodeURIComponent(avatarId)}`, { method: "DELETE" });
}

/** Starts a talking-avatar video of one answer (its voice reply is reused). */
export function createAnswerVideo(cloneId: string, conversationId: string, messageId: string): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>(`${avatarPath(cloneId)}/video`, {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, message_id: messageId }),
  });
}

export function createTestVideo(cloneId: string, text: string): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>(`${avatarPath(cloneId)}/test`, { method: "POST", body: JSON.stringify({ text }) });
}

export function getAvatarJob(cloneId: string, jobId: string): Promise<AvatarJob> {
  return apiFetch<AvatarJob>(`${avatarPath(cloneId)}/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
}

export function cancelAvatarJob(cloneId: string, jobId: string): Promise<AvatarJob> {
  return apiFetch<AvatarJob>(`${avatarPath(cloneId)}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

// --- Authentication (session lives in an HttpOnly cookie set by the API) ---

export function registerAccount(input: RegisterInput): Promise<User> {
  return apiFetch<User>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ ...input, full_name: input.full_name.trim() || null }),
  });
}

export function login(input: LoginInput): Promise<User> {
  return apiFetch<User>("/api/auth/login", { method: "POST", body: JSON.stringify(input) });
}

export function logout(): Promise<void> {
  return apiFetch<void>("/api/auth/logout", { method: "POST" });
}

/** The logged-in user, or null when there is no valid session. */
export async function getCurrentUser(): Promise<User | null> {
  try {
    return await apiFetch<User>("/api/auth/me", { cache: "no-store" });
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return null;
    throw error;
  }
}

export function updateProfile(update: ProfileUpdate): Promise<User> {
  return apiFetch<User>("/api/users/me", { method: "PATCH", body: JSON.stringify(update) });
}

export function changePassword(change: PasswordChange): Promise<void> {
  return apiFetch<void>("/api/auth/change-password", { method: "POST", body: JSON.stringify(change) });
}

// --- Sharing (owner only) ---

export function getPublicSettings(cloneId: string): Promise<PublicSettings> {
  return apiFetch<PublicSettings>(`${clonePath(cloneId)}/public-settings`, { cache: "no-store" });
}

export function updatePublicSettings(cloneId: string, update: PublicSettingsUpdate): Promise<PublicSettings> {
  return apiFetch<PublicSettings>(`${clonePath(cloneId)}/public-settings`, { method: "PATCH", body: JSON.stringify(update) });
}

export function changeSlug(cloneId: string, slug: string): Promise<PublicSettings> {
  return apiFetch<PublicSettings>(`${clonePath(cloneId)}/slug`, { method: "PATCH", body: JSON.stringify({ slug }) });
}

export function setDocumentVisibility(cloneId: string, documentId: string, visibility: ContentVisibility): Promise<DocumentListItem> {
  return apiFetch<DocumentListItem>(`${documentPath(cloneId, documentId)}/visibility`, {
    method: "PATCH",
    body: JSON.stringify({ visibility }),
  });
}

export function setMemoryVisibility(cloneId: string, memoryId: string, visibility: ContentVisibility): Promise<CloneMemory> {
  return apiFetch<CloneMemory>(`${memoryPath(cloneId, memoryId)}/visibility`, {
    method: "PATCH",
    body: JSON.stringify({ visibility }),
  });
}
