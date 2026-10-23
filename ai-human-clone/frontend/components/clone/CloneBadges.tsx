import { STATUSES, VISIBILITIES, labelFor } from "@/lib/clone-options";
import { cn } from "@/lib/utils";
import type { CloneStatus, Visibility } from "@/types/clone";

const STATUS_STYLES: Record<CloneStatus, string> = {
  active: "border-emerald-500/40 text-emerald-300",
  draft: "border-amber-400/40 text-amber-300",
  disabled: "border-rose-500/40 text-rose-300",
};

const badge = "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium";

export function StatusBadge({ status }: { status: CloneStatus }) {
  return <span className={cn(badge, STATUS_STYLES[status])}>{labelFor(STATUSES, status)}</span>;
}

export function VisibilityBadge({ visibility }: { visibility: Visibility }) {
  return <span className={cn(badge, "border-border text-muted")}>{labelFor(VISIBILITIES, visibility)}</span>;
}
