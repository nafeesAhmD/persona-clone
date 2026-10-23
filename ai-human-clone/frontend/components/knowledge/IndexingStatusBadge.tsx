import { INDEXING_LABELS } from "@/lib/knowledge";
import { cn } from "@/lib/utils";
import type { IndexingStatus } from "@/types/clone";

const ICONS: Record<IndexingStatus, string> = { not_indexed: "○", indexing: "⏳", indexed: "✓", indexing_failed: "⚠" };

const STYLES: Record<IndexingStatus, string> = {
  not_indexed: "border-border text-muted",
  indexing: "border-amber-400/40 text-amber-300",
  indexed: "border-cyan/40 text-cyan",
  indexing_failed: "border-rose-500/40 text-rose-300",
};

export function IndexingStatusBadge({ status }: { status: IndexingStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium", STYLES[status])}>
      <span aria-hidden>{ICONS[status]}</span>
      {INDEXING_LABELS[status]}
    </span>
  );
}
