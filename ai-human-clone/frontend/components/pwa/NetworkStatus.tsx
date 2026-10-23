"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { PwaToast } from "@/components/pwa/PwaToast";
import { BACK_ONLINE_EVENT, OFFLINE_MESSAGE } from "@/lib/pwa/network";

function subscribe(onChange: () => void) {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

const getOnline = () => navigator.onLine;
const getServerOnline = () => true;

const BACK_ONLINE_VISIBLE_MS = 3000;

/**
 * Offline banner. When the connection comes back it refreshes server data
 * (router.refresh() re-runs GET requests only; nothing is re-sent) and fires
 * the "ahc:back-online" window event so screens can reload their own data.
 */
export function NetworkStatus() {
  const router = useRouter();
  const online = useSyncExternalStore(subscribe, getOnline, getServerOnline);
  const wasOffline = useRef(false);
  const [showBackOnline, setShowBackOnline] = useState(false);

  useEffect(() => {
    if (!online) {
      wasOffline.current = true;
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    router.refresh();
    window.dispatchEvent(new Event(BACK_ONLINE_EVENT));
    const show = window.setTimeout(() => setShowBackOnline(true), 0);
    const hide = window.setTimeout(() => setShowBackOnline(false), BACK_ONLINE_VISIBLE_MS);
    return () => {
      window.clearTimeout(show);
      window.clearTimeout(hide);
    };
  }, [online, router]);

  if (!online) {
    return (
      <PwaToast tone="warning">
        <p>{OFFLINE_MESSAGE}</p>
      </PwaToast>
    );
  }
  if (showBackOnline) {
    return (
      <PwaToast tone="success">
        <p>You&apos;re back online.</p>
      </PwaToast>
    );
  }
  return null;
}
