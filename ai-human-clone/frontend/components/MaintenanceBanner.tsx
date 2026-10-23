"use client";

import { useEffect, useState } from "react";

import { getPlatformStatus } from "@/lib/adminApi";

/** A banner while an administrator has maintenance mode on (checked every minute). */
export function MaintenanceBanner() {
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      getPlatformStatus()
        .then((status) => !cancelled && setMessage(status.maintenance_mode ? status.message : null))
        .catch(() => undefined); // the API being down is shown elsewhere
    check();
    const timer = window.setInterval(check, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!message) return null;
  return (
    <div role="status" className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-center text-sm text-amber-200">
      {message}
    </div>
  );
}
