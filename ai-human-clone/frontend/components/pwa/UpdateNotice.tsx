"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PwaToast, toastPrimaryButton, toastSecondaryButton } from "@/components/pwa/PwaToast";
import { canUseServiceWorker, pageIsSafeToReload, serviceWorkerUrl, unregisterInDevelopment } from "@/lib/pwa/client";
import { nextUpdateStep } from "@/lib/pwa/update";

const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000;
const SAFE_RELOAD_POLL_MS = 1500;

type Phase = "idle" | "available" | "deferred" | "dismissed";

/**
 * Registers /sw.js (production, secure contexts only) and handles updates:
 * a new version waits until the user taps "Update now"; the page then reloads once
 * the new worker takes over, but never while the user is typing or a form is busy.
 */
export function UpdateNotice() {
  const [phase, setPhase] = useState<Phase>("idle");
  const waiting = useRef<ServiceWorker | null>(null);
  const userAskedToUpdate = useRef(false);
  const skipWaitingSent = useRef(false);
  const reloading = useRef(false);

  useEffect(() => {
    if (!canUseServiceWorker()) {
      void unregisterInDevelopment();
      return;
    }
    let cancelled = false;
    let registration: ServiceWorkerRegistration | null = null;
    let lastCheck = Date.now();

    const offer = (worker: ServiceWorker | null) => {
      // Only an update if a worker already controls the page (not the very first install).
      if (!worker || !navigator.serviceWorker.controller || cancelled) return;
      if (waiting.current !== worker) skipWaitingSent.current = false; // an even newer version
      waiting.current = worker;
      setPhase((current) => (current === "idle" || current === "dismissed" ? "available" : current));
    };

    const watchInstalling = (reg: ServiceWorkerRegistration) => {
      const worker = reg.installing;
      worker?.addEventListener("statechange", () => {
        if (worker.state === "installed") offer(reg.waiting ?? worker);
      });
    };

    const onVisible = () => {
      if (document.visibilityState === "visible" && registration && Date.now() - lastCheck > UPDATE_CHECK_INTERVAL_MS) {
        lastCheck = Date.now();
        registration.update().catch(() => undefined);
      }
    };

    navigator.serviceWorker
      .register(serviceWorkerUrl(), { scope: "/", updateViaCache: "none" })
      .then((reg) => {
        if (cancelled) return;
        registration = reg;
        if (reg.waiting) offer(reg.waiting);
        if (reg.installing) watchInstalling(reg);
        reg.addEventListener("updatefound", () => watchInstalling(reg));
      })
      .catch(() => undefined); // never block the app over a service worker

    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  /**
   * After "Update now": wait until the page is safe to reload, THEN activate the waiting
   * worker (SKIP_WAITING) and reload when it takes over. Activating first would run this
   * (old) page on the new worker, which deletes the old build's caches, and would switch
   * other open tabs too, while the user is still finishing a draft.
   */
  const proceed = useCallback(() => {
    if (reloading.current || !userAskedToUpdate.current) return;
    const worker = waiting.current;
    const step = nextUpdateStep({
      safe: pageIsSafeToReload(),
      workerWaiting: Boolean(worker && worker.state !== "redundant" && worker !== navigator.serviceWorker.controller),
      skipWaitingSent: skipWaitingSent.current,
    });
    if (step === "defer") {
      setPhase("deferred");
    } else if (step === "activate") {
      skipWaitingSent.current = true;
      worker?.postMessage({ type: "SKIP_WAITING" }); // the reload happens on controllerchange
    } else if (step === "reload") {
      reloading.current = true;
      window.location.reload();
    }
  }, []);

  // The new worker took over: reload (now, or as soon as it's safe).
  useEffect(() => {
    if (!canUseServiceWorker()) return;
    navigator.serviceWorker.addEventListener("controllerchange", proceed);
    return () => navigator.serviceWorker.removeEventListener("controllerchange", proceed);
  }, [proceed]);

  // Deferred: check again periodically and when focus leaves a field.
  useEffect(() => {
    if (phase !== "deferred") return;
    const timer = window.setInterval(proceed, SAFE_RELOAD_POLL_MS);
    document.addEventListener("focusout", proceed);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("focusout", proceed);
    };
  }, [phase, proceed]);

  const updateNow = () => {
    userAskedToUpdate.current = true;
    proceed();
  };

  if (phase === "available") {
    return (
      <PwaToast>
        <p className="font-medium">New version available</p>
        <p className="mt-0.5 text-muted">Update to get the latest fixes and features.</p>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" onClick={() => setPhase("dismissed")} className={toastSecondaryButton}>
            Later
          </button>
          <button type="button" onClick={updateNow} className={toastPrimaryButton}>
            Update now
          </button>
        </div>
      </PwaToast>
    );
  }
  if (phase === "deferred") {
    return (
      <PwaToast>
        <p>Will update when you&apos;re done.</p>
        <p className="mt-0.5 text-muted">Finish or send what you&apos;re writing; the app reloads right after.</p>
      </PwaToast>
    );
  }
  return null;
}
