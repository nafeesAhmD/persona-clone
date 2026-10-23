"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { forgetLastChat } from "@/components/mobile/lastChat";

/** Log out from any navigation surface: forget device-local hints, end the session, go to /login. */
export function useLogout() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  const run = useCallback(async () => {
    setLoggingOut(true);
    forgetLastChat(user?.id);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
      router.push("/login");
    }
  }, [user?.id, logout, router]);

  return { logout: run, loggingOut };
}
