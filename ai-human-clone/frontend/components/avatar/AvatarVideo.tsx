"use client";

import { useEffect, useRef, useState } from "react";

import { loadMedia } from "@/lib/api";
import { jobPhase, jobStage, useAvatarJob } from "@/lib/useAvatarJob";

interface AvatarVideoProps {
  cloneId: string;
  jobId: string;
  /** Poster image URL (shown before playing), e.g. the clone's picture. */
  poster?: string | null;
  /** A protected API path for the poster (loaded with the session cookie). */
  posterPath?: string | null;
  /** Offered when the video fails or has expired: e.g. play the voice reply instead. */
  onFallback?: () => void;
  fallbackLabel?: string;
  /** Make a new video after this one failed. */
  onRetry?: () => void;
}

type FullscreenVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };

const PHASE_ICON = { queued: "⏳", processing: "⚙", completed: "✓", failed: "⚠" } as const;

/**
 * A talking-avatar video answer: progress while it renders, then a mobile-friendly
 * player (responsive, poster, controls, playsInline). It never autoplays with sound:
 * the viewer taps to play. Always labelled as AI.
 */
export function AvatarVideo({ cloneId, jobId, poster, posterPath, onFallback, fallbackLabel = "Play voice instead", onRetry }: AvatarVideoProps) {
  const { job, error } = useAvatarJob(cloneId, jobId);
  const [src, setSrc] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);
  const [protectedPoster, setProtectedPoster] = useState<string | null>(null);
  const [canFullscreen, setCanFullscreen] = useState(false);
  const videoRef = useRef<FullscreenVideo>(null);
  const videoUrl = job?.status === "completed" && !job.expired ? job.video_url : null;

  useEffect(() => {
    if (!videoUrl) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    loadMedia(videoUrl, "The video has expired or isn't available.")
      .then((url) => {
        if (cancelled) return URL.revokeObjectURL(url);
        objectUrl = url;
        setLoadError(null);
        setSrc(url);
      })
      .catch((err: unknown) => !cancelled && setLoadError(err instanceof Error ? err.message : "The video couldn't be loaded."));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [videoUrl, attempt]);

  useEffect(() => {
    if (!posterPath) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    loadMedia(posterPath)
      .then((url) => {
        if (cancelled) return URL.revokeObjectURL(url);
        objectUrl = url;
        setProtectedPoster(url);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [posterPath]);

  function checkFullscreen() {
    const video = videoRef.current;
    // Fullscreen: the standard API, or iOS Safari's video-only fullscreen.
    setCanFullscreen(Boolean(video && ((typeof video.requestFullscreen === "function" && document.fullscreenEnabled !== false) || typeof video.webkitEnterFullscreen === "function")));
  }

  function play() {
    const video = videoRef.current;
    if (!video) return;
    setStarted(true);
    video.play().catch(() => setStarted(false)); // refused: the tap overlay stays
  }

  function fullscreen() {
    const video = videoRef.current;
    if (!video) return;
    if (typeof video.requestFullscreen === "function" && document.fullscreenEnabled !== false) video.requestFullscreen().catch(() => video.webkitEnterFullscreen?.());
    else video.webkitEnterFullscreen?.();
  }

  const phase = jobPhase(job, Boolean(error));
  const failed = phase === "failed" || Boolean(loadError);
  const working = !failed && !src;
  const posterUrl = protectedPoster ?? poster ?? undefined;

  return (
    <figure className="w-full max-w-sm overflow-hidden rounded-2xl border border-accent/30 bg-surface" aria-label="AI-generated avatar video">
      {src ? (
        <div className="relative">
          {/* No captions track: the same words are shown as text right beside the video. */}
          <video
            ref={videoRef}
            src={src}
            poster={posterUrl}
            controls={started}
            playsInline
            preload="metadata"
            onLoadedMetadata={checkFullscreen}
            onPlay={() => {
              setPlaying(true);
              setStarted(true);
            }}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            className="aspect-square w-full bg-black object-cover"
          />
          {!started && (
            <button
              type="button"
              onClick={play}
              className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/35 text-sm font-medium text-white"
              aria-label="Play the avatar video"
            >
              <span className="grid h-16 w-16 place-items-center rounded-full bg-white/90 text-2xl text-black shadow-lg" aria-hidden>
                ▶
              </span>
              Tap to play
            </button>
          )}
        </div>
      ) : (
        <div
          className="relative flex aspect-square w-full flex-col items-center justify-center gap-3 bg-surface-raised bg-cover bg-center p-4 text-center"
          style={posterUrl ? { backgroundImage: `linear-gradient(rgba(11,13,20,.75), rgba(11,13,20,.75)), url("${posterUrl.replace(/["\\]/g, "")}")` } : undefined}
        >
          {working ? (
            <>
              <span className="h-8 w-8 animate-spin rounded-full border-2 border-accent/30 border-t-accent motion-reduce:animate-none" aria-hidden />
              <p className="text-sm text-gray-100" aria-live="polite">
                <span aria-hidden>{PHASE_ICON[phase]} </span>
                {job?.status === "completed" ? "Loading video…" : jobStage(job)}
              </p>
              {job?.status === "processing" && (
                <div
                  className="h-1.5 w-3/4 overflow-hidden rounded-full bg-border"
                  role="progressbar"
                  aria-label="Video progress"
                  aria-valuenow={job.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="h-full bg-accent transition-all" style={{ width: `${job.progress}%` }} />
                </div>
              )}
            </>
          ) : (
            <>
              <p className="text-sm text-amber-200" role="alert">
                <span aria-hidden>⚠ </span>
                {loadError ?? error ?? job?.error_message ?? jobStage(job)}
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {loadError && (
                  <button
                    type="button"
                    onClick={() => {
                      setLoadError(null);
                      setAttempt((n) => n + 1);
                    }}
                    className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-xs text-gray-100 hover:border-accent"
                  >
                    ↻ Retry
                  </button>
                )}
                {!loadError && onRetry && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-xs text-gray-100 hover:border-accent"
                  >
                    ↻ Make the video again
                  </button>
                )}
                {onFallback && (
                  <button
                    type="button"
                    onClick={onFallback}
                    className="inline-flex min-h-11 items-center rounded-full border border-accent/40 px-4 text-xs text-accent-soft hover:bg-accent/10"
                  >
                    ▶ {fallbackLabel}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
      <figcaption className="flex items-center gap-2 px-3 py-1.5 text-[11px] font-medium text-accent-soft">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
        <span className="flex-1">AI-generated avatar{src ? (playing ? " · playing" : "") : ` · ${phase}`}</span>
        {src && canFullscreen && (
          <button
            type="button"
            onClick={fullscreen}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-xs text-muted hover:text-white md:min-h-8"
            aria-label="Watch full screen"
          >
            ⛶ Full screen
          </button>
        )}
      </figcaption>
    </figure>
  );
}
