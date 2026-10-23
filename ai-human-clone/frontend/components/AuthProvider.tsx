"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, AUTH_EXPIRED_EVENT, getCurrentUser, logout as logoutRequest } from "@/lib/api";
import type { User } from "@/types/auth";

/** The API couldn't be reached (as opposed to "you're not logged in"). */
function isConnectionProblem(error: unknown): boolean {
  return error instanceof ApiError && ["offline", "network", "timeout", "unavailable"].includes(error.kind);
}

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  /** True when the API ended the session (401), as opposed to the user logging out. */
  sessionExpired: boolean;
  /** Re-check the session with the API (e.g. after login or a profile update). */
  refresh: () => Promise<User | null>;
  /** Store a user returned by login/register/profile update without another request. */
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Holds the current user. The session itself is an HttpOnly cookie that only the
 * browser and API see; this state is just what the API reported from /api/auth/me.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [sessionExpired, setSessionExpired] = useState(false);
  // The /api/auth/me request in flight, shared so a retry never starts a second one.
  const inFlight = useRef<Promise<User | null> | null>(null);

  const setUser = useCallback((next: User | null) => {
    setUserState(next);
    setStatus(next ? "authenticated" : "anonymous");
    setSessionExpired(false);
  }, []);

  const fetchCurrentUser = useCallback(() => {
    inFlight.current ??= getCurrentUser().finally(() => {
      inFlight.current = null;
    });
    return inFlight.current;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const current = await fetchCurrentUser();
      setUser(current);
      return current;
    } catch (error) {
      // No connection: keep the current state (don't sign the user out because the
      // phone is offline); the check runs again when the connection returns.
      if (!isConnectionProblem(error)) setUser(null);
      return null;
    }
  }, [fetchCurrentUser, setUser]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }, [setUser]);

  // Initial session check. State is set in the promise callback, not synchronously.
  useEffect(() => {
    let cancelled = false;
    const check = () =>
      fetchCurrentUser()
        .then((current) => !cancelled && setUser(current))
        // Offline or the API is down: stay "loading" instead of treating the user as
        // logged out (which would send them to /login), and check again once online.
        .catch((error) => !cancelled && !isConnectionProblem(error) && setUser(null));
    check();
    window.addEventListener("online", check);
    return () => {
      cancelled = true;
      window.removeEventListener("online", check);
    };
  }, [fetchCurrentUser, setUser]);

  // A 401 from any API call (session expired or revoked elsewhere) signs this tab out;
  // RequireAuth then sends the user to /login and back here afterwards.
  useEffect(() => {
    const onExpired = () => {
      setUser(null);
      setSessionExpired(true);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [setUser]);

  const value = useMemo(
    () => ({ user, status, sessionExpired, refresh, setUser, logout }),
    [user, status, sessionExpired, refresh, setUser, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** Only allow same-site relative paths as post-login destinations (no open redirects). */
export function safeNextPath(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}
