"use client";

import { cn } from "@/lib/utils";

/**
 * Fixed stack for PWA notices, just below the top bar: at the bottom it would cover
 * submit buttons and the chat composer. Under the drawer (z-50), over the bars (z-30).
 */
export function PwaToastStack({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "pointer-events-none fixed inset-x-0 z-40 flex flex-col items-center gap-2",
        "top-[calc(var(--app-header-h,4rem)+0.5rem)]",
        "pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]",
      )}
    >
      {children}
    </div>
  );
}

interface PwaToastProps {
  children: React.ReactNode;
  tone?: "default" | "warning" | "success";
  /** "status" (polite) for most notices; "alert" for urgent ones. */
  role?: "status" | "alert";
  className?: string;
}

export function PwaToast({ children, tone = "default", role = "status", className }: PwaToastProps) {
  return (
    <div
      role={role}
      aria-live={role === "alert" ? "assertive" : "polite"}
      className={cn(
        "pointer-events-auto w-full max-w-md rounded-xl border px-4 py-3 text-sm shadow-lg shadow-black/40 backdrop-blur",
        tone === "warning" && "border-amber-500/40 bg-amber-950/90 text-amber-100",
        tone === "success" && "border-emerald-500/40 bg-emerald-950/90 text-emerald-100",
        tone === "default" && "border-border bg-surface-raised/95 text-white",
        className,
      )}
    >
      {children}
    </div>
  );
}

export const toastPrimaryButton =
  "inline-flex min-h-11 items-center justify-center rounded-lg bg-accent px-4 text-sm font-semibold text-ink hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft";
export const toastSecondaryButton =
  "inline-flex min-h-11 items-center justify-center rounded-lg px-3 text-sm text-muted hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft";
