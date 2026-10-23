"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = "checking" | "online" | "offline";

const LABELS: Record<Status, string> = {
  checking: "Checking API…",
  online: "API online",
  offline: "API offline",
};

export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((res) => !cancelled && setStatus(res.status === "healthy" ? "online" : "offline"))
      .catch(() => !cancelled && setStatus("offline"));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === "online" && "bg-emerald-400",
          status === "offline" && "bg-rose-400",
          status === "checking" && "animate-pulse bg-muted",
        )}
      />
      {LABELS[status]}
    </span>
  );
}
