"use client";

import { useState } from "react";

import { ErrorNote, Loading, PageHeader, Panel, StatCard, Table, inputClass, useAdminData } from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

const UNIT: Record<string, [string, string]> = {
  LLM_REQUEST: ["est. input tokens", "est. output tokens"],
  STT_REQUEST: ["audio seconds", ""],
  TTS_REQUEST: ["characters", ""],
  AVATAR_JOB: ["", "video seconds"],
};

export default function AdminUsagePage() {
  const [days, setDays] = useState(7);
  const { data, error, loading } = useAdminData(() => adminApi.usage(days), [days]);
  const peak = Math.max(1, ...(data?.per_day.map((d) => d.requests) ?? [1]));

  return (
    <>
      <PageHeader title="Usage" description="Aggregated requests per feature and provider.">
        <select aria-label="Period" className={inputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={1}>Last 24 hours</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </PageHeader>
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <StatCard label="Requests" value={data.total_requests.toLocaleString()} />
            <StatCard
              label="Estimated cost"
              value={data.estimated_total_cost !== null ? `$${data.estimated_total_cost.toFixed(4)}` : "Not configured"}
              hint={data.cost_configured ? "Estimate only" : "Set *_COST_PER_UNIT to estimate"}
            />
            <StatCard label="Features used" value={new Set(data.rows.map((r) => r.event_type)).size} />
          </div>
          <p className="text-xs text-muted">{data.note}</p>

          <Table head={["Feature", "Provider", "Requests", "Failed", "Input", "Output", "Avg time", "Est. cost"]} empty={data.rows.length === 0}>
            {data.rows.map((r) => (
              <tr key={`${r.event_type}-${r.provider}`}>
                <td className="px-3 py-2 font-mono text-xs text-white">{r.event_type}</td>
                <td className="px-3 py-2">{r.provider ?? "—"}</td>
                <td className="px-3 py-2">{r.requests}</td>
                <td className={`px-3 py-2 ${r.failed ? "text-rose-300" : "text-muted"}`}>{r.failed}</td>
                <td className="px-3 py-2 text-muted">
                  {r.input_units ? `${r.input_units.toLocaleString()} ${UNIT[r.event_type]?.[0] ?? ""}` : "—"}
                </td>
                <td className="px-3 py-2 text-muted">
                  {r.output_units ? `${r.output_units.toLocaleString()} ${UNIT[r.event_type]?.[1] ?? ""}` : "—"}
                </td>
                <td className="px-3 py-2 text-muted">{r.avg_duration_ms !== null ? `${Math.round(r.avg_duration_ms)} ms` : "—"}</td>
                <td className="px-3 py-2 text-muted">{r.estimated_cost !== null ? `$${r.estimated_cost.toFixed(4)}` : "—"}</td>
              </tr>
            ))}
          </Table>

          <Panel title="Requests per day">
            {data.per_day.length === 0 ? (
              <p className="text-sm text-muted">No usage in this period.</p>
            ) : (
              <ul className="space-y-1">
                {data.per_day.map((d) => (
                  <li key={d.day} className="flex items-center gap-3 text-xs">
                    <span className="w-24 shrink-0 text-muted">{d.day}</span>
                    <span className="h-3 rounded bg-accent/60" style={{ width: `${(d.requests / peak) * 100}%` }} />
                    <span className="text-white">{d.requests}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {([["Top users", data.top_users], ["Top AI Clones", data.top_clones]] as const).map(([title, list]) => (
              <Panel key={title} title={title}>
                {list.length === 0 ? (
                  <p className="text-sm text-muted">No data.</p>
                ) : (
                  <ol className="space-y-1 text-sm">
                    {list.map((entry) => (
                      <li key={entry.id} className="flex justify-between gap-2">
                        <span className="truncate">{entry.label}</span>
                        <span className="text-muted">{entry.requests}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </Panel>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
