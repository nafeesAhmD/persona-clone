"use client";

import Link from "next/link";

import { EmptyState, LoadingBlock, btnSecondary, useApiData } from "@/components/analytics/ui";
import { agentApi } from "@/lib/agentApi";
import { failureRatePercent, formatDurationMs, sortToolUsage, toolTitle } from "@/lib/agentStatus";
import { formatCompact, formatNumber } from "@/lib/usage";
import type { AgentAnalyticsRange } from "@/types/agent";
import type { AnalyticsRange } from "@/types/analytics";

/** The agent endpoint knows 7d / 30d / 90d; shorter periods show the last 7 days. */
export function agentRangeFor(range: AnalyticsRange): AgentAnalyticsRange {
  return range === "30d" || range === "90d" ? range : "7d";
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-surface/60 p-3">
      <p className="truncate text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-0.5 text-xl font-semibold ${tone === "bad" ? "text-rose-300" : "text-white"}`}>{value}</p>
      {hint && <p className="truncate text-xs text-muted">{hint}</p>}
    </div>
  );
}

/** Agent tasks of a clone: counts, outcomes, timings and the most-used tools. Counts only. */
export function AgentAnalyticsSection({ cloneId, range }: { cloneId: string; range: AnalyticsRange }) {
  const agentRange = agentRangeFor(range);
  const stats = useApiData(() => agentApi.analytics(cloneId, agentRange), `${cloneId}:${agentRange}`);
  const encodedId = encodeURIComponent(cloneId);

  if (stats.error && !stats.data) {
    const message = stats.error instanceof Error && stats.error.message ? stats.error.message : "Agent statistics couldn't be loaded.";
    return (
      <div className="space-y-2 text-sm">
        <p className="text-muted">{message}</p>
        <button type="button" onClick={stats.reload} className={btnSecondary}>
          Try again
        </button>
      </div>
    );
  }
  if (!stats.data) return <LoadingBlock label="Loading agent statistics…" />;

  const data = stats.data;
  const unsuccessful = data.failed + data.timeout;
  const tools = sortToolUsage(data.tools).slice(0, 6);

  if (data.executions === 0) {
    return (
      <EmptyState title="No agent tasks yet" body="Run a task on the AI Agent page or use Agent Mode in the chat.">
        <Link href={`/clone/${encodedId}/agent`} className={btnSecondary}>
          Open AI Agent
        </Link>
      </EmptyState>
    );
  }

  return (
    <div className={`space-y-4 ${stats.loading ? "opacity-60 transition-opacity" : ""}`}>
      {range !== agentRange && <p className="text-xs text-muted">Agent numbers cover the last 7 days.</p>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Tasks" value={formatCompact(data.executions)} hint={formatNumber(data.executions)} />
        <Stat label="Completed" value={formatCompact(data.completed)} />
        <Stat label="Failed" value={formatCompact(data.failed)} tone={data.failed > 0 ? "bad" : undefined} />
        <Stat label="Timed out" value={formatCompact(data.timeout)} tone={data.timeout > 0 ? "bad" : undefined} />
        <Stat label="Cancelled" value={formatCompact(data.cancelled)} />
        <Stat
          label="Avg. duration"
          value={formatDurationMs(data.avg_duration_ms) || "—"}
          hint={data.avg_steps !== null && data.avg_steps !== undefined ? `${formatNumber(data.avg_steps, 1)} steps on average` : undefined}
        />
      </div>
      {unsuccessful > 0 && (
        <p className="text-xs text-muted">
          <span aria-hidden="true">⚠ </span>
          {formatNumber(Math.round((unsuccessful / data.executions) * 100))}% of tasks failed or timed out.
        </p>
      )}

      <div>
        <h3 className="text-sm font-semibold text-white">Most-used tools</h3>
        {tools.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No tools were used in this period.</p>
        ) : (
          <ul className="mt-2 divide-y divide-border text-sm">
            {tools.map((tool) => {
              const rate = failureRatePercent(tool);
              return (
                <li key={tool.tool} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 py-2">
                  <span className="min-w-0 break-words font-medium text-white">{toolTitle(tool.tool)}</span>
                  <span className="text-xs text-muted">
                    {formatNumber(tool.calls)} {tool.calls === 1 ? "call" : "calls"} ·{" "}
                    <span className={rate > 0 ? "text-rose-300" : undefined}>
                      {rate > 0 && <span aria-hidden="true">⚠ </span>}
                      {rate}% failed
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
