/**
 * Browser-side service-worker helpers (Phase 15). Uses DOM APIs, so it is not part
 * of the node unit tests; the decisions it relies on live in the pure modules.
 */

import { isSafeToReload, type FocusSnapshot } from "./update.ts";
import { isBusy } from "@/lib/busy";

const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";
const API_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").origin;
  } catch {
    return "";
  }
})();

/** /sw.js?v=<build>&api=<api origin>: a new build changes the URL, which triggers an update. */
export function serviceWorkerUrl(): string {
  const params = new URLSearchParams({ v: BUILD_ID });
  if (API_ORIGIN) params.set("api", API_ORIGIN);
  return `/sw.js?${params.toString()}`;
}

/** Service workers run only in production builds, in secure contexts (https or localhost). */
export function canUseServiceWorker(): boolean {
  return (
    process.env.NODE_ENV === "production" &&
    typeof window !== "undefined" &&
    window.isSecureContext &&
    "serviceWorker" in navigator
  );
}

/** In development, remove a worker left over from a production run on the same origin. */
export async function unregisterInDevelopment(): Promise<void> {
  if (process.env.NODE_ENV === "production" || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(
      registrations
        .filter((r) => (r.active ?? r.waiting ?? r.installing)?.scriptURL.includes("/sw.js"))
        .map((r) => r.unregister()),
    );
  } catch {
    // Ignore: not critical.
  }
}

/** Ask every service worker of this site to drop its caches (called on logout, defence in depth). */
export async function clearServiceWorkerCaches(): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    for (const worker of [registration?.active, registration?.waiting]) worker?.postMessage({ type: "CLEAR_CACHES" });
  } catch {
    // Ignore.
  }
}

function focusSnapshot(): FocusSnapshot {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return { tagName: null };
  const tagName = el.tagName.toLowerCase();
  if (el.isContentEditable) return { tagName, isContentEditable: true, value: el.textContent };
  if (el instanceof HTMLInputElement) return { tagName, inputType: el.type, value: el.value };
  if (el instanceof HTMLTextAreaElement) return { tagName, value: el.value };
  return { tagName };
}

/**
 * Is it OK to reload now? Not while the user types, a draft is unsent, or any element
 * says it's busy: data-busy="true" (forms submitting, recordings, live calls) or aria-busy.
 */
export function pageIsSafeToReload(): boolean {
  const busy = isBusy() || Boolean(document.querySelector('[data-busy="true"], form[aria-busy="true"]'));
  const hasDraft = Array.from(document.querySelectorAll("textarea")).some((t) => t.value.trim().length > 0);
  return isSafeToReload({ focus: focusSnapshot(), busy, hasDraft });
}
