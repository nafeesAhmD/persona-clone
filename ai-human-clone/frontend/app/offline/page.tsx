import type { Metadata } from "next";

import { OfflineRetry } from "@/components/pwa/OfflineRetry";

export const metadata: Metadata = {
  title: "Offline · Clone Me",
  robots: { index: false, follow: false },
};

// Prerendered at build time: the service worker precaches this HTML and serves it
// when a page can't be loaded. It must work without the API.
export const dynamic = "force-static";

export default function OfflinePage() {
  return (
    <main
      className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center px-4 py-24 text-center"
      // Readable even if the stylesheet couldn't be loaded.
      style={{ textAlign: "center", padding: "6rem 1rem" }}
    >
      <div
        aria-hidden
        className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-soft to-accent text-lg font-bold text-ink"
      >
        AI
      </div>
      <h1 className="mt-6 text-xl font-semibold">You are offline.</h1>
      <p className="mt-2 text-sm text-muted">Some features may be unavailable. Check your connection and try again.</p>
      <OfflineRetry />
    </main>
  );
}
