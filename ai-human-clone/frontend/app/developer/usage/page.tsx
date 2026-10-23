"use client";

import { useState } from "react";

import { ErrorNote, Loading, PageHeader, Panel, StatCard, Table, inputClass, useAdminData } from "@/components/admin/ui";
import { OwnerSelect, useOrganizations } from "@/components/developer/ui";
import { developerApi } from "@/lib/developerApi";

export default function DeveloperUsagePage() {
  const orgs = useOrganizations();
  const [owner, setOwner] = useState("");
  const [days, setDays] = useState(30);
  const { data, error, loading } = useAdminData(() => developerApi.usage(days, owner || undefined), [days, owner]);
  const total = data?.per_day.reduce((sum, d) => sum + d.requests, 0) ?? 0;
  const errors = data?.per_day.reduce((sum, d) => sum + d.errors, 0) ?? 0;
  const peak = Math.max(1, ...(data?.per_day.map((d) => d.requests) ?? [1]));

  return (
    <>
      <PageHeader title="API usage" description="Requests made with your API keys.">
        <div className="flex flex-wrap items-center gap-2">
          <OwnerSelect orgs={orgs} value={owner} onChange={setOwner} id="usage-owner" />
          <label htmlFor="usage-period" className="sr-only">
            Period
          </label>
          <select id="usage-period" className={inputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={1}>Today</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>
      </PageHeader>
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <StatCard label="Requests" value={total.toLocaleString()} />
            <StatCard label="Errors" value={errors.toLocaleString()} tone={errors > 0 ? "warn" : undefined} />
            <StatCard label="Error rate" value={total ? `${((errors / total) * 100).toFixed(1)}%` : "—"} />
          </div>

          <Panel title="Requests per day">
            {total === 0 ? (
              <p className="text-sm text-muted">No API requests in this period.</p>
            ) : (
              <ul className="space-y-1" aria-label="Requests per day">
                {data.per_day.map((d) => (
                  <li key={d.day} className="flex items-center gap-3 text-xs">
                    <span className="w-24 shrink-0 text-muted">{d.day}</span>
                    <span className="flex h-3 min-w-0 flex-1 items-center" aria-hidden="true">
                      <span className="flex h-3 overflow-hidden rounded" style={{ width: `${(d.requests / peak) * 100}%` }}>
                        <span className="h-full bg-accent/60" style={{ width: `${d.requests ? ((d.requests - d.errors) / d.requests) * 100 : 0}%` }} />
                        <span className="h-full bg-rose-500/70" style={{ width: `${d.requests ? (d.errors / d.requests) * 100 : 0}%` }} />
                      </span>
                    </span>
                    <span className="w-24 shrink-0 text-right text-white">
                      {d.requests}
                      {d.errors > 0 && <span className="text-rose-300"> ({d.errors} err)</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 flex gap-4 text-xs text-muted">
              <span className="flex items-center gap-1">
                <span className="inline-block h-2 w-3 rounded bg-accent/60" aria-hidden="true" /> successful
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-2 w-3 rounded bg-rose-500/70" aria-hidden="true" /> errors
              </span>
            </p>
          </Panel>

          <section aria-labelledby="by-endpoint">
            <h2 id="by-endpoint" className="mb-2 text-sm font-semibold text-white">
              By endpoint
            </h2>
            <Table head={["Endpoint", "Requests", "Errors", "Avg time"]} empty={data.by_endpoint.length === 0}>
              {data.by_endpoint.map((row) => (
                <tr key={row.endpoint}>
                  <td className="px-3 py-2 font-mono text-xs text-white">{row.endpoint}</td>
                  <td className="px-3 py-2">{row.requests}</td>
                  <td className={`px-3 py-2 ${row.errors ? "text-rose-300" : "text-muted"}`}>{row.errors}</td>
                  <td className="px-3 py-2 text-muted">
                    {row.avg_duration_ms !== null ? `${Math.round(row.avg_duration_ms)} ms` : "—"}
                  </td>
                </tr>
              ))}
            </Table>
          </section>

          <section aria-labelledby="by-key">
            <h2 id="by-key" className="mb-2 text-sm font-semibold text-white">
              By API key
            </h2>
            <Table head={["Key", "Prefix", "Requests"]} empty={data.by_key.length === 0}>
              {data.by_key.map((row) => (
                <tr key={row.key_id}>
                  <td className="px-3 py-2 text-white">{row.name}</td>
                  <td className="px-3 py-2 font-mono text-xs text-muted">{row.key_prefix ? `${row.key_prefix}…` : "—"}</td>
                  <td className="px-3 py-2">{row.requests}</td>
                </tr>
              ))}
            </Table>
          </section>
        </div>
      )}
    </>
  );
}
