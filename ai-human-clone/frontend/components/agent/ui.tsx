"use client";

import { useId } from "react";

import { riskIcon, riskLabel, normalizeRisk, statusIcon, statusLabel, statusTone } from "@/lib/agentStatus";
import { cn } from "@/lib/utils";

const STATUS_STYLES = {
  active: "border-cyan/40 bg-cyan/10 text-cyan",
  waiting: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  error: "border-rose-500/40 bg-rose-500/10 text-rose-200",
  neutral: "border-border bg-surface text-muted",
} as const;

/** Task status: icon + text, never color alone. */
export function AgentStatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        STATUS_STYLES[statusTone(status)],
        className,
      )}
    >
      <span aria-hidden="true">{statusIcon(status)}</span>
      <span className="truncate">{statusLabel(status)}</span>
    </span>
  );
}

const RISK_STYLES = {
  low: "border-emerald-500/40 text-emerald-200",
  medium: "border-amber-400/40 text-amber-200",
  high: "border-rose-500/40 text-rose-200",
  critical: "border-rose-500/60 bg-rose-500/10 text-rose-100",
} as const;

/** Risk: icon + text, never color alone. */
export function RiskBadge({ risk, className }: { risk: string | null | undefined; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium",
        RISK_STYLES[normalizeRisk(risk)],
        className,
      )}
    >
      <span aria-hidden="true">{riskIcon(risk)}</span>
      {riskLabel(risk)}
    </span>
  );
}

/**
 * An on/off switch with a visible label (44px touch target). `description` is read
 * together with the label; `lockedReason` explains why it can't be changed.
 */
export function Switch({
  label,
  description,
  checked,
  onChange,
  disabled = false,
  lockedReason,
  busy = false,
  className,
}: {
  label: string;
  description?: React.ReactNode;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  lockedReason?: string | null;
  busy?: boolean;
  className?: string;
}) {
  const labelId = useId();
  const descriptionId = useId();
  const off = disabled || Boolean(lockedReason) || busy;
  return (
    <div className={cn("flex items-start justify-between gap-3", className)}>
      <div className="min-w-0 flex-1 py-1">
        <p id={labelId} className="text-sm font-medium text-white">
          {label}
        </p>
        {(description || lockedReason) && (
          <div id={descriptionId} className="mt-0.5 text-xs text-muted">
            {description}
            {lockedReason && (
              <p className="mt-0.5 text-amber-200">
                <span aria-hidden="true">🔒 </span>
                {lockedReason}
              </p>
            )}
          </div>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={description || lockedReason ? descriptionId : undefined}
        aria-busy={busy || undefined}
        disabled={off}
        onClick={() => onChange(!checked)}
        className="inline-flex min-h-11 min-w-14 shrink-0 items-center justify-center rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span
          aria-hidden="true"
          className={cn(
            "relative inline-flex h-7 w-12 items-center rounded-full border transition-colors motion-reduce:transition-none",
            checked ? "border-accent bg-accent" : "border-border bg-surface",
          )}
        >
          <span
            className={cn(
              "absolute h-5 w-5 rounded-full bg-white shadow transition-transform motion-reduce:transition-none",
              checked ? "translate-x-6" : "translate-x-1",
            )}
          />
        </span>
        <span className="sr-only">{checked ? "On" : "Off"}</span>
      </button>
    </div>
  );
}
