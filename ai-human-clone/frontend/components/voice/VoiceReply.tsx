"use client";

import { useEffect, useRef, useState } from "react";

import { loadAudio } from "@/lib/api";

interface VoiceReplyProps {
  /** API path of the generated speech (fetched with the session cookie). */
  audioUrl: string;
  /** Try to start playing as soon as it's ready (browsers may still block it). */
  autoPlay?: boolean;
  label?: string;
}

/** "▶ Play response", then a normal audio player (play/pause, progress, volume). */
export function VoiceReply({ audioUrl, autoPlay = false, label = "Play response" }: VoiceReplyProps) {
  const [src, setSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(autoPlay);
  const [error, setError] = useState<string | null>(null);
  const [playWhenReady, setPlayWhenReady] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const objectUrl = useRef<string | null>(null);

  async function load(play: boolean) {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const url = await loadAudio(audioUrl);
      objectUrl.current = url;
      setPlayWhenReady(play);
      setSrc(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The voice response couldn't be loaded.");
    } finally {
      setLoading(false);
    }
  }

  // Auto-play: fetch right away (state changes only once the download settles).
  useEffect(() => {
    if (!autoPlay) return;
    let cancelled = false;
    loadAudio(audioUrl)
      .then((url) => {
        if (cancelled) return URL.revokeObjectURL(url);
        objectUrl.current = url;
        setPlayWhenReady(true);
        setSrc(url);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "The voice response couldn't be loaded.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // Only when the audio first appears: turning auto-play on later doesn't replay old answers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  useEffect(
    () => () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [],
  );

  useEffect(() => {
    if (src && playWhenReady) {
      // Autoplay can be refused (no recent user gesture); the controls stay available.
      audioRef.current?.play().catch(() => undefined);
    }
  }, [src, playWhenReady]);

  if (error) return <p className="text-[11px] text-rose-300">{error}</p>;
  if (!src) {
    return (
      <button
        type="button"
        onClick={() => load(true)}
        disabled={loading}
        className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 px-3 py-1 text-xs text-accent-soft transition hover:bg-accent/10 disabled:opacity-60"
      >
        <span aria-hidden>▶</span> {loading ? "Loading voice…" : label}
      </button>
    );
  }
  // No captions track: the same words are shown as text right above the player.
  return <audio ref={audioRef} controls src={src} className="h-9 w-full max-w-xs" aria-label="AI voice response" />;
}
