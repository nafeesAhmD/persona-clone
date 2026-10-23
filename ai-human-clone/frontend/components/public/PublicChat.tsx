"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { CloneAvatar } from "@/components/CloneAvatar";
import { RealtimeVoicePanel } from "@/components/realtime/RealtimeVoicePanel";
import { FormattedText } from "@/components/FormattedText";
import { ApiError } from "@/lib/api";
import {
  createPublicVideo,
  endPublicSession,
  getPublicJob,
  getPublicSession,
  loadPublicMedia,
  loadSessionToken,
  saveSessionToken,
  sendPublicMessage,
  speakPublicMessage,
  transcribePublic,
} from "@/lib/publicApi";
import { MAX_RECORDING_SECONDS, useVoiceRecorder } from "@/lib/useVoiceRecorder";
import { cn } from "@/lib/utils";
import type { PublicClone, PublicMessage } from "@/types/public";

type Mode = "text" | "voice" | "avatar";

interface ChatItem extends PublicMessage {
  error?: boolean;
  sources?: string[];
  audioSrc?: string | null;
  videoSrc?: string | null;
  mediaState?: string | null; // "Generating voice…", "Generating video…", an error…
}

const POLL_MS = 2000;
const GIVE_UP_MS = 5 * 60 * 1000;

function local(role: ChatItem["role"], content: string, extra: Partial<ChatItem> = {}): ChatItem {
  return { id: crypto.randomUUID(), role, content, input_mode: "text", created_at: new Date().toISOString(), ...extra };
}

/** A visitor's conversation with a public clone. No login; the session lives in this browser. */
export function PublicChat({ clone }: { clone: PublicClone }) {
  const slug = clone.slug;
  const [token, setToken] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [messagesLeft, setMessagesLeft] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("text");
  const [processingVoice, setProcessingVoice] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const recorder = useVoiceRecorder();
  const bottomRef = useRef<HTMLDivElement>(null);
  const objectUrls = useRef<string[]>([]);

  const modes: Mode[] = ["text", ...(clone.voice_enabled ? (["voice"] as Mode[]) : []), ...(clone.avatar_enabled ? (["avatar"] as Mode[]) : [])];

  // Restore this browser's conversation with the clone, if it's still valid.
  useEffect(() => {
    const saved = loadSessionToken(slug);
    if (!saved) return;
    let cancelled = false;
    getPublicSession(slug, saved)
      .then((session) => {
        if (cancelled) return;
        setToken(saved);
        setMessages(session.messages);
        setMessagesLeft(session.messages_left);
      })
      .catch(() => !cancelled && saveSessionToken(slug, null));
    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => () => objectUrls.current.forEach((url) => URL.revokeObjectURL(url)), []);

  const update = useCallback((id: string, change: Partial<ChatItem>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...change } : m)));
  }, []);

  async function addVoice(session: string, messageId: string) {
    update(messageId, { mediaState: "Generating voice…" });
    try {
      const { audio_url } = await speakPublicMessage(slug, session, messageId);
      const src = await loadPublicMedia(audio_url, session);
      objectUrls.current.push(src);
      update(messageId, { audioSrc: src, mediaState: null });
    } catch (err) {
      update(messageId, { mediaState: err instanceof Error ? err.message : "Voice generation temporarily unavailable" });
    }
  }

  async function addVideo(session: string, messageId: string) {
    update(messageId, { mediaState: "Queued…" });
    try {
      const { job_id } = await createPublicVideo(slug, session, messageId);
      const started = Date.now();
      for (;;) {
        const job = await getPublicJob(slug, session, job_id);
        if (job.status === "completed" && job.video_url) {
          const src = await loadPublicMedia(job.video_url, session);
          objectUrls.current.push(src);
          update(messageId, { videoSrc: src, mediaState: null });
          return;
        }
        if (job.status === "failed" || job.status === "cancelled") {
          update(messageId, { mediaState: job.error_message ?? "The avatar video couldn't be generated." });
          return;
        }
        if (Date.now() - started > GIVE_UP_MS) {
          update(messageId, { mediaState: "The video is taking too long. Please try again later." });
          return;
        }
        update(messageId, { mediaState: job.status === "queued" ? "Queued…" : job.progress < 80 ? "Generating video…" : "Almost ready…" });
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      }
    } catch (err) {
      update(messageId, { mediaState: err instanceof Error ? err.message : "The avatar video couldn't be generated." });
    }
  }

  async function send(text: string, inputMode: "text" | "voice" = "text") {
    if (!text || sending) return;
    setError(null);
    setInput("");
    setSending(true);
    setMessages((prev) => [...prev, local("user", text, { input_mode: inputMode })]);
    try {
      let reply;
      try {
        reply = await sendPublicMessage(slug, text, token, inputMode);
      } catch (err) {
        // The saved conversation expired: start a fresh one with the same question.
        if (!(err instanceof ApiError && err.status === 404 && token)) throw err;
        saveSessionToken(slug, null);
        setToken(null);
        reply = await sendPublicMessage(slug, text, null, inputMode);
      }
      setToken(reply.session_id);
      saveSessionToken(slug, reply.session_id);
      setMessagesLeft(reply.messages_left);
      const answer: ChatItem = { ...reply.message, sources: reply.sources.map((s) => s.title) };
      setMessages((prev) => [...prev, answer]);
      if (mode === "avatar" && clone.avatar_enabled) void addVideo(reply.session_id, answer.id);
      else if ((mode === "voice" || inputMode === "voice") && clone.voice_enabled) void addVoice(reply.session_id, answer.id);
    } catch (err) {
      const reason = err instanceof Error ? err.message : "Something went wrong.";
      setMessages((prev) => [...prev, local("assistant", reason, { error: true })]);
    } finally {
      setSending(false);
    }
  }

  async function sendRecording(recording: Blob | null) {
    if (!recording) return;
    setProcessingVoice(true);
    try {
      const { text } = await transcribePublic(slug, recording);
      setProcessingVoice(false);
      await send(text, "voice");
    } catch (err) {
      recorder.setError(err instanceof Error ? err.message : "The recording couldn't be processed.");
    } finally {
      setProcessingVoice(false);
    }
  }

  async function newConversation() {
    if (sending) return;
    if (token) await endPublicSession(slug, token).catch(() => undefined);
    saveSessionToken(slug, null);
    setToken(null);
    setMessages([]);
    setMessagesLeft(null);
    setError(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void send(input.trim());
  }

  const busy = sending || processingVoice;

  return (
    <section aria-label={`Chat with ${clone.name}`} className="flex min-h-[28rem] flex-col rounded-2xl compact:min-h-0 border border-border bg-surface-raised">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 text-xs">
        <span className="rounded-full border border-accent/40 px-2.5 py-1 font-medium text-accent-soft">AI-generated responses</span>
        {messagesLeft !== null && <span className="text-muted">{messagesLeft} messages left in this conversation</span>}
        <button
          type="button"
          onClick={newConversation}
          disabled={busy || messages.length === 0}
          className="ml-auto min-h-11 rounded-full md:min-h-9 border border-border px-3 py-1.5 text-muted hover:border-accent hover:text-white disabled:opacity-40"
        >
          New conversation
        </button>
      </div>

      <div className="flex max-h-[60dvh] flex-1 flex-col gap-4 overflow-y-auto px-4 py-5 compact:max-h-[45dvh]" aria-live="polite">
        {messages.length === 0 && (
          <p className="m-auto max-w-sm text-center text-sm text-muted">
            Ask {clone.name} about their work. Answers come only from information the owner made public.
          </p>
        )}
        {messages.map((message) => {
          const isUser = message.role === "user";
          return (
            <div key={message.id} className={cn("flex items-end gap-3", isUser && "flex-row-reverse")}>
              {!isUser && <CloneAvatar name={clone.name} size="sm" />}
              <div className={cn("flex max-w-[85%] flex-col gap-1", isUser && "items-end")}>
                {isUser && message.input_mode === "voice" && (
                  <p className="px-1 text-[11px] text-muted"><span aria-hidden>🎤</span> Voice message</p>
                )}
                <div
                  className={cn(
                    "whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                    isUser && "rounded-br-sm bg-accent text-ink",
                    !isUser && !message.error && "rounded-bl-sm border border-border bg-surface text-gray-100",
                    message.error && "rounded-bl-sm border border-rose-500/30 bg-rose-500/10 text-rose-200",
                  )}
                >
                  {isUser ? message.content : <FormattedText text={message.content} />}
                </div>
                {message.videoSrc && (
                  <figure className="w-full max-w-xs overflow-hidden rounded-2xl border border-accent/30">
                    <video src={message.videoSrc} controls playsInline className="aspect-square w-full bg-black object-cover" />
                    <figcaption className="px-3 py-1.5 text-[11px] font-medium text-accent-soft">AI-generated avatar</figcaption>
                  </figure>
                )}
                {message.audioSrc && (
                  <audio src={message.audioSrc} controls className="h-9 w-full max-w-xs" aria-label="AI voice response" />
                )}
                {message.mediaState && <p className="px-1 text-[11px] text-amber-200" aria-live="polite">{message.mediaState}</p>}
                {message.sources && message.sources.length > 0 && (
                  <p className="px-1 text-[11px] text-muted">Based on: {message.sources.join(", ")}</p>
                )}
              </div>
            </div>
          );
        })}
        {sending && <p className="pl-11 text-xs text-muted">{clone.name} is thinking…</p>}
        <div ref={bottomRef} />
      </div>

      <div className="space-y-2 border-t border-border px-4 py-3">
        {error && <p className="text-xs text-rose-300" role="alert">{error}</p>}
        {recorder.error && <p className="text-xs text-rose-300" role="alert">{recorder.error}</p>}
        {processingVoice && <p className="text-xs text-muted" aria-live="polite">Processing voice…</p>}
        {clone.realtime_voice_available && (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setLiveOpen((open) => !open)}
              disabled={!token}
              aria-expanded={liveOpen}
              className="min-h-11 rounded-full border border-emerald-400/50 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-400/10 disabled:opacity-50 md:min-h-9"
            >
              {liveOpen ? "Close live voice" : "🎙️ Live voice"}
            </button>
            {!token && <p className="text-[11px] text-muted">Send a first message to start a live voice conversation.</p>}
            {liveOpen && token && (
              <RealtimeVoicePanel target={{ kind: "public", slug, token }} cloneName={clone.name} compact />
            )}
          </div>
        )}
        {modes.length > 1 && (
          <div className="flex flex-wrap items-center gap-2 text-xs" role="group" aria-label="Response mode">
            <span className="text-muted">Reply as:</span>
            {modes.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={mode === option}
                onClick={() => setMode(option)}
                className={cn(
                  "min-h-11 rounded-full border px-3 py-1.5 md:min-h-9",
                  mode === option ? "border-accent bg-accent/15 text-accent-soft" : "border-border text-muted hover:text-white",
                )}
              >
                {option === "text" ? "Text" : option === "voice" ? "🔊 Voice" : "🎬 Avatar"}
              </button>
            ))}
          </div>
        )}
        {recorder.state !== "idle" ? (
          <div className="flex items-center gap-3 rounded-xl border border-rose-500/40 bg-rose-500/5 px-4 py-3" role="status">
            <span className="h-3 w-3 shrink-0 animate-pulse rounded-full bg-rose-500" aria-hidden />
            <p className="min-w-0 flex-1 text-sm">
              {recorder.state === "requesting" ? "Waiting for microphone permission…" : `Listening… ${recorder.seconds}s / ${MAX_RECORDING_SECONDS}s`}
            </p>
            <button type="button" onClick={async () => sendRecording(await recorder.stopRecording())} disabled={recorder.state !== "recording"} className="min-h-11 rounded-lg bg-rose-600 px-4 text-sm text-white disabled:opacity-50">
              Stop
            </button>
            <button type="button" onClick={recorder.cancelRecording} className="min-h-11 rounded-lg border border-border px-4 text-sm text-muted">
              Cancel
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex items-end gap-2">
            {clone.voice_enabled && (
              <button
                type="button"
                onClick={() => recorder.startRecording(sendRecording)}
                disabled={busy}
                aria-label="Record a voice message"
                className="min-h-11 min-w-11 rounded-xl border border-border bg-surface px-3.5 py-3 text-sm hover:border-accent disabled:opacity-50"
              >
                <span aria-hidden>🎤</span>
              </button>
            )}
            <label htmlFor="public-chat-input" className="sr-only">Message</label>
            <textarea
              id="public-chat-input"
              rows={1}
              value={input}
              maxLength={4000}
              enterKeyHint="send"
              autoComplete="off"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input.trim());
                }
              }}
              placeholder={`Ask ${clone.name}…`}
              className="max-h-40 min-w-0 flex-1 resize-none rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none placeholder:text-muted focus:border-accent"
            />
            <button
              type="submit"
              disabled={!input.trim() || busy}
              className="min-h-11 rounded-xl bg-accent px-4 py-3 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50 sm:px-5"
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </form>
        )}
        <p className="text-[11px] text-muted">This is an AI representation, not the real person. Don&apos;t share passwords or private details.</p>
      </div>
    </section>
  );
}
