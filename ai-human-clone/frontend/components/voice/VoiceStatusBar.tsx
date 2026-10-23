"use client";

import { cn } from "@/lib/utils";
import {
  STAGE_INFO,
  type VoiceState,
  formatSeconds,
  isCancellable,
  voiceErrorMessage,
} from "@/lib/voiceStates";

interface VoiceStatusBarProps {
  state: VoiceState;
  seconds: number;
  maxSeconds: number;
  /** Stop recording and send it (Listening), or send the parked recording (Recorded). */
  onSend: () => void;
  onCancel: () => void;
  /** Re-send the same recording after an upload/provider failure (only on tap). */
  onRetry?: () => void;
  onDismiss: () => void;
}

const buttonBase =
  "inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl px-4 text-sm font-medium transition disabled:opacity-50";

/** One voice turn's progress: text + icon for every step (never color alone), with Cancel. */
export function VoiceStatusBar({ state, seconds, maxSeconds, onSend, onCancel, onRetry, onDismiss }: VoiceStatusBarProps) {
  const info = STAGE_INFO[state.stage];
  const isError = state.stage === "error";
  const recording = state.stage === "listening";
  const spinner = info.busy && !recording && state.stage !== "recorded";

  return (
    <div
      className={cn(
        "rounded-xl border px-3 py-2.5 sm:px-4",
        isError ? "border-rose-500/40 bg-rose-500/10" : recording ? "border-rose-500/40 bg-rose-500/5" : "border-border bg-surface-raised",
      )}
      role={isError ? "alert" : "status"}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          {recording ? (
            <span className="relative flex h-3 w-3 shrink-0" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-500 opacity-75 motion-reduce:animate-none" />
              <span className="relative inline-flex h-3 w-3 rounded-full bg-rose-500" />
            </span>
          ) : spinner ? (
            <span className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent/30 border-t-accent motion-reduce:animate-none" aria-hidden />
          ) : (
            <span aria-hidden className="shrink-0">{info.icon}</span>
          )}
          <span className="min-w-0">
            <span className="font-medium">{info.label}</span>
            {recording && (
              <span className="ml-2 tabular-nums text-muted">
                {formatSeconds(seconds)} / {formatSeconds(maxSeconds)}
              </span>
            )}
          </span>
        </p>
        <div className="flex flex-wrap gap-2">
          {recording && (
            <button type="button" onClick={onSend} className={cn(buttonBase, "bg-rose-600 text-white hover:bg-rose-500")}>
              <span aria-hidden className="mr-1.5">■</span>Stop &amp; send
            </button>
          )}
          {state.stage === "recorded" && (
            <button type="button" onClick={onSend} className={cn(buttonBase, "bg-accent text-ink hover:bg-accent/90")}>
              Send
            </button>
          )}
          {isError && onRetry && (
            <button type="button" onClick={onRetry} className={cn(buttonBase, "bg-accent text-ink hover:bg-accent/90")}>
              Try again
            </button>
          )}
          {isCancellable(state.stage) ? (
            <button
              type="button"
              onClick={onCancel}
              className={cn(buttonBase, "border border-border text-muted hover:text-white")}
            >
              {state.stage === "recorded" ? "Discard" : "Cancel"}
            </button>
          ) : (
            (isError || state.stage === "complete") && (
              <button
                type="button"
                onClick={onDismiss}
                className={cn(buttonBase, "border border-border text-muted hover:text-white")}
              >
                {isError ? "Dismiss" : "OK"}
              </button>
            )
          )}
        </div>
      </div>
      {isError && state.error && (
        <p className="mt-2 text-xs text-rose-200">
          {voiceErrorMessage(state.error)}
          {state.detail && <span className="mt-0.5 block text-rose-200/70">{state.detail}</span>}
        </p>
      )}
    </div>
  );
}
