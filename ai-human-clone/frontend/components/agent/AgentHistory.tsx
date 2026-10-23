"use client";

import Link from "next/link";
import { useState } from "react";

import { AgentStatusBadge } from "@/components/agent/ui";
import { Card, EmptyState, LoadingBlock, btnSecondary, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { agentApi } from "@/lib/agentApi";
import { pageCount } from "@/lib/agentStatus";

const PAGE_SIZE = 10;

const SOURCE_LABELS: Record<string, string> = { app: "App", api: "Developer API", public: "Public" };

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** Past agent tasks of a clone, newest first, a page at a time. */
export function AgentHistory({ cloneId, version }: { cloneId: string; version: number }) {
  const [page, setPage] = useState(1);
  const history = useApiData(() => agentApi.executions(cloneId, page, PAGE_SIZE), `${cloneId}:${page}:${version}`);
  const pages = history.data ? pageCount(history.data.total, history.data.limit || PAGE_SIZE) : 1;
  const encodedId = encodeURIComponent(cloneId);

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-white">Task history</h2>
        {history.data && <span className="text-xs text-muted">{history.data.total} total</span>}
      </div>
      <div className="mt-3" aria-busy={history.loading}>
        {history.error && !history.data ? (
          <ApiErrorState error={history.error} thing="task history" onRetry={history.reload} />
        ) : !history.data ? (
          <LoadingBlock label="Loading task history…" />
        ) : history.data.items.length === 0 ? (
          <EmptyState title="No tasks yet" body="Tasks you run here or in Agent Mode in the chat appear here." />
        ) : (
          <ul className={`space-y-2 ${history.loading ? "opacity-60" : ""}`}>
            {history.data.items.map((item) => (
              <li key={item.id}>
                <Link
                  href={`/clone/${encodedId}/agent/executions/${encodeURIComponent(item.id)}`}
                  className="block min-h-11 rounded-xl border border-border bg-surface/60 p-3 hover:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft"
                >
                  <p className="line-clamp-2 break-words text-sm text-white">{item.goal}</p>
                  <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                    <AgentStatusBadge status={item.status} />
                    <span>{item.total_steps === 1 ? "1 step" : `${item.total_steps} steps`}</span>
                    <span>· {SOURCE_LABELS[item.source] ?? item.source}</span>
                    {item.created_at && <time dateTime={item.created_at}>· {formatWhen(item.created_at)}</time>}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      {pages > 1 && (
        <nav aria-label="Task history pages" className="mt-3 flex items-center justify-between gap-2">
          <button type="button" className={btnSecondary} disabled={page <= 1 || history.loading} onClick={() => setPage((p) => p - 1)}>
            <span aria-hidden="true">←</span> Newer
          </button>
          <span className="text-xs text-muted" aria-live="polite">
            Page {page} of {pages}
          </span>
          <button type="button" className={btnSecondary} disabled={page >= pages || history.loading} onClick={() => setPage((p) => p + 1)}>
            Older <span aria-hidden="true">→</span>
          </button>
        </nav>
      )}
    </Card>
  );
}
