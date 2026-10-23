"use client";

import Link from "next/link";
import { useEffect } from "react";

import { safeRelativePath } from "@/lib/pwa/paths";

/**
 * The page the service worker could not load (it adds <meta name="ahc-offline-from">
 * when it serves /offline in its place). Read once when this chunk loads, before
 * hydration can touch <head>.
 */
const retryTarget: string =
  typeof document === "undefined"
    ? "/"
    : safeRelativePath(document.querySelector('meta[name="ahc-offline-from"]')?.getAttribute("content"), "/");

function retry() {
  window.location.assign(retryTarget);
}

/** Retry button for the offline page; also retries by itself when the connection returns. */
export function OfflineRetry() {
  useEffect(() => {
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, []);

  return (
    <div className="mt-6 flex flex-col items-center gap-3">
      <button
        type="button"
        onClick={retry}
        className="min-h-11 min-w-32 rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-ink hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft"
      >
        Retry
      </button>
      {/* Works without JavaScript too. */}
      <noscript>
        <Link href="/" className="text-sm text-accent-soft underline">
          Retry
        </Link>
      </noscript>
    </div>
  );
}
