"use client";

import { useEffect, useState } from "react";

import { CheckIcon, ShareIcon } from "@/components/mobile/icons";

type State = "idle" | "copied" | "failed";

/**
 * "Share this AI Clone": the system share sheet where available (phones), otherwise
 * copy the link. Only used on public clone pages, which are public by definition.
 */
export function ShareButton({ title, text, className }: { title: string; text?: string; className?: string }) {
  const [state, setState] = useState<State>("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2500);
    return () => clearTimeout(timer);
  }, [state]);

  async function share() {
    const url = window.location.href.split("#")[0];
    if (typeof navigator.share === "function") {
      try {
        await navigator.share({ title, text, url });
        return;
      } catch (error) {
        // The user closed the share sheet: nothing to do. Other errors: fall back to copying.
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={share}
        className={
          className ??
          "flex min-h-12 items-center justify-center gap-2 rounded-xl border border-border px-5 font-medium text-gray-100 hover:border-accent sm:min-h-11"
        }
      >
        {state === "copied" ? <CheckIcon className="h-5 w-5 text-emerald-300" /> : <ShareIcon className="h-5 w-5" />}
        {state === "copied" ? "Link copied" : "Share this AI Clone"}
      </button>
      <span role="status" aria-live="polite" className="sr-only">
        {state === "copied" ? "Link copied to the clipboard." : state === "failed" ? "Couldn't copy. Copy the address bar link instead." : ""}
      </span>
      {state === "failed" && (
        <p className="text-xs text-amber-300">Couldn&apos;t copy automatically. Copy the link from the address bar.</p>
      )}
    </>
  );
}
