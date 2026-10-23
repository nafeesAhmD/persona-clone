"use client";

import { useEffect, useRef, useState } from "react";

import { speakInBrowser } from "@/lib/browserVoice";

interface BrowserVoiceButtonProps {
  text: string;
  /** Start right away (the user just asked to hear it, or auto-play is on). */
  autoStart?: boolean;
}

/** Plays an answer with the browser's own voice when the AI voice isn't available. */
export function BrowserVoiceButton({ text, autoStart = false }: BrowserVoiceButtonProps) {
  const [speaking, setSpeaking] = useState(autoStart);
  const stop = useRef<(() => void) | null>(null);

  function start() {
    stop.current?.();
    setSpeaking(true);
    stop.current = speakInBrowser(text, () => {
      stop.current = null;
      setSpeaking(false);
    });
  }

  useEffect(() => {
    if (autoStart) {
      // State changes only through the end callback.
      stop.current = speakInBrowser(text, () => {
        stop.current = null;
        setSpeaking(false);
      });
    }
    return () => stop.current?.();
    // Only once, when the fallback first appears.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <button
      type="button"
      onClick={() => (speaking ? stop.current?.() : start())}
      className="inline-flex items-center gap-1.5 rounded-full border border-cyan/40 px-3 py-1 text-xs text-cyan transition hover:bg-cyan/10"
    >
      <span aria-hidden>{speaking ? "■" : "▶"}</span>
      {speaking ? "Stop" : "Play with browser voice"}
    </button>
  );
}
