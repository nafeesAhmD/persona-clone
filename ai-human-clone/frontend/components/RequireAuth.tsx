"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { StatusMessage } from "@/components/StatusMessage";

/**
 * Client-side guard: sends logged-out visitors to /login?next=<this page>.
 * It only improves the UX. Every protected API also checks the session itself.
 */

/** If the API is unreachable the session stays "loading"; after this long show a retry
 *  instead of "Checking your session…" forever (the browser is online, the server isn't). */
const CHECK_TIMEOUT_MS = 10_000;

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, sessionExpired, refresh } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const wasAuthenticated = useRef(false);
  const [timedOut, setTimedOut] = useState(false);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (status === "authenticated") {
      wasAuthenticated.current = true;
    } else if (status === "anonymous") {
      // Logging out from this page goes to a plain /login. Arriving logged out, or
      // the session expiring here, remembers the page (with its query string) so the
      // user comes back to it after logging in.
      const loggedOut = wasAuthenticated.current && !sessionExpired;
      const here = `${pathname}${window.location.search}`;
      router.replace(loggedOut ? "/login" : `/login?next=${encodeURIComponent(here)}`);
    }
  }, [status, sessionExpired, router, pathname]);

  // The AuthProvider deliberately keeps "loading" while the API is unreachable,
  // so cap the wait here and offer a retry. The flag is only read in the
  // status === "loading" branch, so it needs no reset when the check resolves.
  useEffect(() => {
    if (status !== "loading") return;
    const timer = window.setTimeout(() => setTimedOut(true), CHECK_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [status]);

  if (status === "authenticated") {
    return <>{children}</>;
  }
  if (status === "loading") {
    if (timedOut) {
      return (
        <StatusMessage
          title="Can't reach the server"
          body="We couldn't check your session. Check your connection, then try again."
        >
          {/* refresh() reuses a check that is still in flight; while the server stays
              unreachable this screen stays up instead of falling back to "Checking…". */}
          <button
            type="button"
            disabled={retrying}
            onClick={() => {
              setRetrying(true);
              void refresh().finally(() => setRetrying(false));
            }}
            className="rounded-lg bg-accent px-4 py-2 font-medium text-ink hover:bg-accent/90 disabled:opacity-60"
          >
            {retrying ? "Trying again…" : "Try again"}
          </button>
        </StatusMessage>
      );
    }
    return <StatusMessage title="Checking your session…" />;
  }
  return <StatusMessage title="Redirecting to login…" />;
}
