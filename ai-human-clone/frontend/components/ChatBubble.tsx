import Link from "next/link";

import { CloneAvatar } from "@/components/CloneAvatar";
import { FormattedText } from "@/components/FormattedText";
import { AvatarVideo } from "@/components/avatar/AvatarVideo";
import { BrowserVoiceButton } from "@/components/voice/BrowserVoiceButton";
import { VoiceReply } from "@/components/voice/VoiceReply";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/clone";

interface ChatBubbleProps {
  message: ChatMessage;
  cloneId: string;
  cloneName: string;
  autoPlay?: boolean;
  /** The viewer owns the clone: sources link to the knowledge pages. */
  isOwner?: boolean;
  /** Poster for avatar videos (the clone's picture). */
  avatarPoster?: string | null;
  /** For an answer to a spoken question that has no audio yet: generate and play it. */
  onListen?: () => void;
  /** Voice reply offered when an avatar video fails. */
  onVoiceFallback?: () => void;
  /** A failed turn: re-send it (only when the user taps Retry). */
  onRetry?: () => void;
  /** Start a new avatar video for this answer after the last one failed. */
  onRetryVideo?: () => void;
}

const pill =
  "inline-flex min-h-11 items-center gap-1.5 rounded-full border px-3.5 text-xs transition md:min-h-8 md:px-3";

export function ChatBubble({
  message,
  cloneId,
  cloneName,
  autoPlay = false,
  isOwner = false,
  avatarPoster,
  onListen,
  onVoiceFallback,
  onRetry,
  onRetryVideo,
}: ChatBubbleProps) {
  const isUser = message.role === "user";
  const hasAudio = Boolean(message.audioUrl || message.audioPending || message.browserVoice);
  const canListen = !isUser && onListen && !hasAudio;
  const fallback = !hasAudio ? onVoiceFallback : undefined;
  const spoken = !isUser && (message.audioUrl || message.audioPending || message.audioError || canListen);
  const sources = message.sources ?? [];
  const hasSources = sources.length > 0 || Boolean(message.memoriesUsed);

  return (
    <div className={cn("flex items-end gap-2 sm:gap-3", isUser && "flex-row-reverse")}>
      {!isUser && (
        <span className="hidden shrink-0 sm:block">
          <CloneAvatar name={cloneName} size="sm" />
        </span>
      )}
      <div className={cn("flex min-w-0 max-w-[88%] flex-col gap-1 sm:max-w-[80%]", isUser && "items-end")}>
        {isUser && message.input_mode === "voice" && (
          <p className="px-1 text-[11px] text-muted">
            <span aria-hidden>🎤</span> Voice message
          </p>
        )}
        {spoken && (
          <p className="px-1 text-[11px] text-muted">
            <span aria-hidden>🔊</span> AI voice response
          </p>
        )}
        <div
          className={cn(
            "whitespace-pre-wrap break-words rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed sm:text-sm",
            isUser && "rounded-br-sm bg-accent text-ink",
            !isUser && !message.error && "rounded-bl-sm border border-border bg-surface-raised text-gray-100",
            message.error && "rounded-bl-sm border border-rose-500/30 bg-rose-500/10 text-rose-200",
          )}
          role={message.error ? "alert" : undefined}
        >
          {message.error && <span className="sr-only">Error: </span>}
          {isUser ? message.content : <FormattedText text={message.content} />}
        </div>
        {message.error && onRetry && (
          <div className="px-1">
            <button
              type="button"
              onClick={onRetry}
              className={cn(pill, "border-rose-400/40 text-rose-200 hover:bg-rose-500/10")}
            >
              <span aria-hidden>↻</span> Retry
            </button>
          </div>
        )}
        {!isUser && message.avatar_job_id && (
          <div className="w-full px-1 pt-1">
            <AvatarVideo
              key={message.avatar_job_id}
              cloneId={cloneId}
              jobId={message.avatar_job_id}
              poster={avatarPoster}
              onFallback={fallback}
              onRetry={onRetryVideo}
            />
          </div>
        )}
        {!isUser && message.avatarError && (
          <div className="flex flex-wrap items-center gap-2 px-1">
            <p className="text-[11px] text-amber-300">Avatar video unavailable: {message.avatarError}</p>
            {onRetryVideo && (
              <button type="button" onClick={onRetryVideo} className={cn(pill, "border-border text-muted hover:text-white")}>
                <span aria-hidden>↻</span> Try video again
              </button>
            )}
            {fallback && (
              <button type="button" onClick={fallback} className={cn(pill, "border-accent/40 text-accent-soft hover:bg-accent/10")}>
                <span aria-hidden>▶</span> Play voice instead
              </button>
            )}
          </div>
        )}
        {!isUser && message.audioPending && (
          <p className="px-1 text-[11px] text-muted" aria-live="polite">
            <span aria-hidden>🔊</span> Generating voice…
          </p>
        )}
        {!isUser && message.audioUrl && (
          <div className="w-full px-1">
            <VoiceReply audioUrl={message.audioUrl} autoPlay={autoPlay || Boolean(message.playNow)} />
          </div>
        )}
        {canListen && (
          <div className="px-1">
            <button type="button" onClick={onListen} className={cn(pill, "border-accent/40 text-accent-soft hover:bg-accent/10")}>
              <span aria-hidden>▶</span> {message.audioError ? "Try voice again" : "Play response"}
            </button>
          </div>
        )}
        {!isUser && message.browserVoice && (
          <div className="px-1">
            <BrowserVoiceButton text={message.content} autoStart={Boolean(message.playNow)} />
          </div>
        )}
        {!isUser && message.audioError && <p className="px-1 text-[11px] text-amber-300">{message.audioError}</p>}
        {!isUser && hasSources && (
          <details className="group px-1 text-[11px] text-muted">
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 md:min-h-6 [&::-webkit-details-marker]:hidden">
              <span aria-hidden className="transition group-open:rotate-90">▸</span>
              {[
                sources.length ? `Sources (${sources.length})` : null,
                message.memoriesUsed ? `Memory used: ${message.memoriesUsed}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </summary>
            {sources.length > 0 && (
              <ul className="mb-1 ml-4 mt-1 space-y-1">
                {sources.map((source) => (
                  <li key={source.document_id} className="break-words">
                    {isOwner ? (
                      <Link
                        href={`/clone/${cloneId}/knowledge/${source.document_id}`}
                        className="inline-flex min-h-8 items-center text-accent-soft hover:underline"
                      >
                        {source.title}
                      </Link>
                    ) : (
                      source.title
                    )}
                  </li>
                ))}
              </ul>
            )}
          </details>
        )}
      </div>
    </div>
  );
}
