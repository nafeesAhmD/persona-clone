"use client";

import { useEffect, useRef } from "react";

import { useAuth } from "@/components/AuthProvider";
import { InstallPrompt } from "@/components/pwa/InstallPrompt";
import { NetworkStatus } from "@/components/pwa/NetworkStatus";
import { PwaToastStack } from "@/components/pwa/PwaToast";
import { UpdateNotice } from "@/components/pwa/UpdateNotice";
import { clearServiceWorkerCaches } from "@/lib/pwa/client";

/**
 * PWA pieces that live once per page: service-worker registration + update notice,
 * install prompt and the offline/network banner (Phase 15). Rendered by app/layout.tsx
 * inside <AuthProvider>.
 */
export function PwaLayer() {
  const { status } = useAuth();
  const previous = useRef(status);

  // Logged out (or the session ended): drop the service worker's caches. They only hold
  // static assets, so this is defence in depth, not the main protection.
  useEffect(() => {
    if (previous.current === "authenticated" && status === "anonymous") void clearServiceWorkerCaches();
    previous.current = status;
  }, [status]);

  return (
    <PwaToastStack>
      <NetworkStatus />
      <UpdateNotice />
      <InstallPrompt />
    </PwaToastStack>
  );
}
