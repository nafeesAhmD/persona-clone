import { STATUS_LABELS } from "@/lib/knowledge";
import { cn } from "@/lib/utils";
import type { DocumentStatus } from "@/types/clone";

const ICONS: Record<DocumentStatus, string> = { pending: "…", processing: "⏳", ready: "✓", failed: "⚠" };

const STYLES: Record<DocumentStatus, string> = {
  pending: "border-border text-muted",
  processing: "border-amber-400/40 text-amber-300",
  ready: "border-emerald-500/40 text-emerald-300",
  failed: "border-rose-500/40 text-rose-300",
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium", STYLES[status])}>
      <span aria-hidden>{ICONS[status]}</span>
      {STATUS_LABELS[status]}
    </span>
  );
}
