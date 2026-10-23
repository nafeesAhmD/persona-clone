"use client";

import { useEffect, useRef } from "react";

import { BACK_ONLINE_EVENT } from "@/lib/pwa/network";

/**
 * Runs `reload` when the browser comes back online (the PWA layer's event).
 * Use it for GET refetches only: never re-send a POST/PATCH/DELETE from here.
 */
export function useBackOnline(reload: () => void) {
  const latest = useRef(reload);
  useEffect(() => {
    latest.current = reload;
  });
  useEffect(() => {
    const handler = () => latest.current();
    window.addEventListener(BACK_ONLINE_EVENT, handler);
    return () => window.removeEventListener(BACK_ONLINE_EVENT, handler);
  }, []);
}
