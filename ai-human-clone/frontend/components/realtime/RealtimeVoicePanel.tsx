"use client";

import { type FormEvent, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { isRetryable, realtimeErrorMessage } from "@/lib/realtime/errors";
import { formatClock } from "@/lib/realtime/session";
import { realtimeSupportProblem, useRealtimeVoice } from "@/lib/realtime/useRealtimeVoice";
import type { RealtimeTarget } from "@/lib/realtimeApi";
import { cn } from "@/lib/utils";
import type { RealtimeSpeechMode } from "@/types/realtime";

interface Props {
  target: RealtimeTarget;
  cloneName: string;
  initialSpeechMode?: RealtimeSpeechMode;
  /** The clone has a cloned voice (else server speech is an AI voice). */
  clonedVoice?: boolean;
  maxUtteranceSeconds?: number;
  maxUtteranceBytes?: number;
  /** Smaller layout inside another page (public chat). */
  compact?: boolean;
}

const PHASE_LABEL: Record<string, string> = {
  idle: "Not connected",
  requesting_mic: "Waiting for microphone permission…",
  connecting: "Connecting…",
  connected: "Connected",
  ending: "Ending…",
  ended: "Session ended",
  failed: "Not connected",
};

const noSubscribe = () => () => undefined;

const ACTIVITY_LABEL = {
  listening: "Listening",
  thinking: "Thinking…",
  speaking: "Speaking",
} as const;

/**
 * A live voice conversation with a clone (Phase 17). The microphone opens only after
 * "Start", nothing plays before that, and every control is a labelled button.
 */
export function RealtimeVoicePanel({
  target,
  cloneName,
  initialSpeechMode = "voice",
  clonedVoice = false,
  maxUtteranceSeconds,
  maxUtteranceBytes,
  compact = false,
}: Props) {
  const voice = useRealtimeVoice(target, { initialSpeechMode, maxUtteranceSeconds, maxUtteranceBytes });
  const { state } = voice;
  const [draft, setDraft] = useState("");
  // Browser-only check; the server render assumes support (no hydration mismatch).
  const unsupported = useSyncExternalStore(
    noSubscribe,
    () => realtimeSupportProblem() !== null,
    () => false,
  );
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [state.transcript]);

  const connected = state.phase === "connected";
  const starting = state.phase === "requesting_mic" || state.phase === "connecting";
  const canStart = state.phase === "idle" || state.phase === "ended" || state.phase === "failed";
  const activity = voice.speaking ? "speaking" : voice.userTalking ? "listening" : state.activity;
  const statusText = connected
    ? state.muted
      ? "Connected · microphone muted"
      : voice.userTalking
        ? "Connected · hearing you…"
        : `Connected · ${ACTIVITY_LABEL[activity]}`
    : PHASE_LABEL[state.phase];
  const errorText = state.error ? state.error.message || realtimeErrorMessage(state.error.code) : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    voice.sendText(draft);
    setDraft("");
  }

  return (
    <section
      className={cn("rounded-2xl border border-border bg-surface-raised", compact ? "p-3" : "p-4 sm:p-6")}
      aria-label={`Live voice conversation with ${cloneName}`}
    >
      <p className="rounded-xl border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-accent-soft sm:text-sm">
        You are talking to an AI representation of {cloneName}, not the real person. Its voice is AI-generated.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
            connected ? "border-emerald-500/40 text-emerald-200" : starting ? "border-amber-500/40 text-amber-200" : "border-border text-muted",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "h-2 w-2 rounded-full",
              connected ? "bg-emerald-400" : starting ? "animate-pulse bg-amber-400" : "bg-slate-500",
            )}
          />
          <span role="status" aria-live="polite">{statusText}</span>
        </span>
        {connected && (
          <span className="text-xs text-muted" aria-label="Session duration">
            {formatClock(voice.elapsed)} / {formatClock(state.maxDurationSeconds)}
          </span>
        )}
        {connected && (
          <span className="flex h-2 w-24 overflow-hidden rounded-full bg-surface" aria-hidden title="Microphone level">
            <span className="h-full bg-accent transition-[width]" style={{ width: `${Math.min(100, Math.round(voice.level * 600))}%` }} />
          </span>
        )}
      </div>

      {connected && (
        <div className="mt-4 flex items-center gap-3" aria-hidden>
          <ActivityDot label="Listening" active={activity === "listening" && !state.muted} tone="emerald" />
          <ActivityDot label="Thinking" active={activity === "thinking"} tone="amber" />
          <ActivityDot label={`${cloneName} speaking`} active={activity === "speaking"} tone="accent" />
        </div>
      )}

      {unsupported && canStart && (
        <p className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-sm text-amber-200" role="alert">
          {realtimeErrorMessage("unsupported")}
        </p>
      )}

      {errorText && (
        <div className="mt-4 flex flex-wrap items-start gap-3 rounded-xl border border-rose-500/40 bg-rose-500/5 px-3 py-2 text-sm text-rose-200" role="alert">
          <p className="min-w-0 flex-1">{errorText}</p>
          {state.phase === "failed" && isRetryable(state.error?.code) && (
            <button type="button" onClick={voice.start} className="min-h-11 rounded-lg border border-rose-400/50 px-3 text-xs hover:bg-rose-500/10 md:min-h-8">
              Try again
            </button>
          )}
          {state.phase !== "failed" && (
            <button type="button" onClick={voice.dismissError} className="min-h-11 rounded-lg px-3 text-xs text-muted hover:text-white md:min-h-8">
              Dismiss
            </button>
          )}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {canStart ? (
          <button
            type="button"
            onClick={voice.start}
            disabled={unsupported}
            className="min-h-11 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {state.phase === "idle" ? "🎙️ Start voice conversation" : "Start a new session"}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={voice.toggleMute}
              disabled={!connected}
              aria-pressed={state.muted}
              className={cn(
                "min-h-11 rounded-xl border px-4 py-2 text-sm disabled:opacity-50",
                state.muted ? "border-amber-500/50 bg-amber-500/10 text-amber-200" : "border-border hover:border-accent",
              )}
            >
              {state.muted ? "🔇 Unmute" : "🎙️ Mute"}
            </button>
            <button
              type="button"
              onClick={voice.interrupt}
              disabled={!connected || (activity !== "speaking" && activity !== "thinking")}
              className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm hover:border-accent disabled:opacity-50"
            >
              ✋ Stop speaking
            </button>
            <button
              type="button"
              onClick={voice.end}
              disabled={state.phase === "ending" || state.phase === "requesting_mic"}
              className="min-h-11 rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white hover:bg-rose-500 disabled:opacity-50"
            >
              End
            </button>
          </>
        )}
      </div>

      <fieldset className="mt-4">
        <legend className="text-xs font-medium text-muted">Voice of the answers</legend>
        <div className="mt-2 inline-flex rounded-xl border border-border bg-surface p-0.5 text-xs" role="radiogroup">
          {(["voice", "browser"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={state.speechMode === mode}
              onClick={() => voice.setSpeechMode(mode)}
              disabled={!connected && !canStart}
              className={cn(
                "min-h-11 rounded-lg px-3 md:min-h-8",
                state.speechMode === mode ? "bg-accent/20 font-medium text-accent-soft" : "text-muted hover:text-white",
              )}
            >
              {mode === "voice" ? (clonedVoice ? "Clone's voice" : "AI voice") : "Browser voice"}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          {state.speechMode === "voice"
            ? clonedVoice
              ? "Answers use the clone's own (AI-cloned) voice. On a server without a GPU each sentence can take a minute to generate."
              : "Answers use the server's AI voice."
            : "Your browser reads the answers instantly, but it is the device's voice, not the clone's voice."}
        </p>
      </fieldset>

      {(state.transcript.length > 0 || connected) && (
        <div className="mt-4">
          <h3 className="text-xs font-medium text-muted">Transcript</h3>
          <ol className={cn("mt-2 space-y-2 overflow-y-auto pr-1 text-sm", compact ? "max-h-56" : "max-h-[45vh]")}>
            {state.transcript.map((entry) => (
              <li key={entry.id} className={cn("flex", entry.role === "you" ? "justify-end" : "justify-start")}>
                <p
                  className={cn(
                    "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2",
                    entry.role === "you" ? "bg-accent/20 text-white" : "border border-border bg-surface",
                  )}
                >
                  <span className="sr-only">{entry.role === "you" ? "You: " : `${cloneName}: `}</span>
                  {entry.text || (entry.streaming ? "…" : "")}
                  {entry.interrupted && <span className="ml-1 text-[11px] text-muted">(interrupted)</span>}
                </p>
              </li>
            ))}
            {connected && state.transcript.length === 0 && (
              <li className="text-xs text-muted">Say something — {cloneName} is listening.</li>
            )}
          </ol>
          <div ref={endRef} />
        </div>
      )}

      {connected && (
        <form onSubmit={submit} className="mt-3 flex gap-2">
          <label htmlFor="realtime-text" className="sr-only">Type a message instead</label>
          <input
            id="realtime-text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={2000}
            placeholder="Or type a message…"
            className="min-h-11 min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 text-sm max-sm:text-base"
          />
          <button type="submit" disabled={!draft.trim()} className="min-h-11 rounded-xl border border-accent/50 px-4 text-sm text-accent-soft disabled:opacity-50">
            Send
          </button>
        </form>
      )}
    </section>
  );
}

function ActivityDot({ label, active, tone }: { label: string; active: boolean; tone: "emerald" | "amber" | "accent" }) {
  const color = tone === "emerald" ? "bg-emerald-400" : tone === "amber" ? "bg-amber-400" : "bg-accent";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", active ? "text-white" : "text-muted")}>
      <span className={cn("h-2.5 w-2.5 rounded-full", active ? `${color} animate-pulse` : "bg-slate-600")} />
      {label}
    </span>
  );
}
