"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { PwaToast, toastPrimaryButton, toastSecondaryButton } from "@/components/pwa/PwaToast";
import {
  INSTALL_DISMISS_KEY,
  installOffer,
  isIosSafari,
  isStandalone,
  parseDismissedAt,
} from "@/lib/pwa/install";

/** Chrome/Edge/Samsung's install event (not in the TS DOM types). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform?: string }>;
}

const PAGE_VIEWS_KEY = "ahc:page-views";
/** Pages where an install card would get in the way. */
// Only on browsing pages: never over a form, an editor or a chat composer.
const INSTALL_PATHS = ["/dashboard", "/clones", "/explore", "/analytics", "/profile"];

function readDismissedAt(): number | null {
  try {
    return parseDismissedAt(window.localStorage.getItem(INSTALL_DISMISS_KEY));
  } catch {
    return null;
  }
}

function writeDismissedAt(now: number) {
  try {
    window.localStorage.setItem(INSTALL_DISMISS_KEY, String(now));
  } catch {
    // Private mode / storage blocked: the card just won't remember.
  }
}

function countPageView(): number {
  try {
    const next = (Number(window.sessionStorage.getItem(PAGE_VIEWS_KEY)) || 0) + 1;
    window.sessionStorage.setItem(PAGE_VIEWS_KEY, String(next));
    return next;
  } catch {
    return 2;
  }
}

const standaloneQuery = "(display-mode: standalone), (display-mode: fullscreen), (display-mode: minimal-ui)";

function subscribeDisplayMode(onChange: () => void) {
  const media = window.matchMedia(standaloneQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function displayModeStandalone(): boolean {
  return (
    window.matchMedia(standaloneQuery).matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/**
 * A small, dismissible "Install Clone Me" card. Uses beforeinstallprompt where
 * the browser supports it; on iOS Safari shows the "Share → Add to Home Screen" hint.
 * Hidden when installed, on the first page view of a session, and for 30 days after
 * "Not now". Never blocks the app.
 */
export function InstallPrompt() {
  const pathname = usePathname();
  const standaloneNow = useSyncExternalStore(subscribeDisplayMode, displayModeStandalone, () => true);
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [view, setView] = useState<{ pageViews: number; dismissedAt: number | null; ios: boolean; now: number } | null>(null);

  useEffect(() => {
    const onPrompt = (event: Event) => {
      event.preventDefault(); // show our own card instead of the browser's mini-infobar
      setDeferred(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setDeferred(null);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  // Count page views per session (client navigations included).
  useEffect(() => {
    const pageViews = countPageView();
    const id = window.setTimeout(
      () =>
        setView({
          pageViews,
          dismissedAt: readDismissedAt(),
          ios: isIosSafari(navigator.userAgent, navigator.maxTouchPoints),
          now: Date.now(),
        }),
      0,
    );
    return () => window.clearTimeout(id);
  }, [pathname]);

  if (!view || !INSTALL_PATHS.includes(pathname ?? "")) return null;

  const offer = installOffer({
    standalone: isStandalone({ displayModeStandalone: standaloneNow, appInstalled: installed }),
    hasDeferredPrompt: deferred !== null,
    iosSafari: view.ios,
    dismissedAt: view.dismissedAt,
    now: view.now,
    pageViews: view.pageViews,
  });
  if (offer === "none") return null;

  const dismiss = () => {
    const now = Date.now();
    writeDismissedAt(now);
    setView((current) => current && { ...current, dismissedAt: now });
  };

  const install = async () => {
    if (!deferred) return;
    const event = deferred;
    setDeferred(null); // the event can be used only once
    try {
      await event.prompt();
      const choice = await event.userChoice;
      if (choice.outcome === "dismissed") dismiss();
    } catch {
      // The browser refused; nothing else to do.
    }
  };

  return (
    <PwaToast className="flex items-start gap-3">
      <div
        aria-hidden
        className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent-soft to-accent text-sm font-bold text-ink"
      >
        AI
      </div>
      <div className="min-w-0 flex-1">
        <p className="font-medium">Install Clone Me</p>
        {offer === "prompt" ? (
          <p className="mt-0.5 text-muted">Open it from your home screen, full screen, like an app.</p>
        ) : (
          <p className="mt-0.5 text-muted">
            Tap <span className="font-medium text-white">Share</span>{" "}
            <ShareIcon /> then <span className="font-medium text-white">Add to Home Screen</span>.
          </p>
        )}
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" onClick={dismiss} className={toastSecondaryButton}>
            Not now
          </button>
          {offer === "prompt" && (
            <button type="button" onClick={install} className={toastPrimaryButton}>
              Install
            </button>
          )}
        </div>
      </div>
    </PwaToast>
  );
}

function ShareIcon() {
  return (
    <svg aria-label="(the square with an arrow)" role="img" viewBox="0 0 24 24" className="inline h-4 w-4 align-text-bottom" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3v12" />
      <path d="m8 7 4-4 4 4" />
      <path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" />
    </svg>
  );
}
