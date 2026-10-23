"use client";

import { useEffect, useRef, useState } from "react";

import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  StatCard,
  SuccessNote,
  Table,
  buttonClass,
  dangerButtonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { adminDeveloperApi } from "@/lib/developerApi";
import type { AdminApiKeyRow } from "@/types/developer";

const LIMIT = 20;
const STATUS_COLOR = { active: "green", revoked: "red", expired: "amber" } as const;

export default function AdminDeveloperPage() {
  const { data: stats, error: statsError, loading: statsLoading, reload: reloadStats } = useAdminData(
    () => adminDeveloperApi.overview(),
    [],
  );
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const { data: keys, error: keysError, loading: keysLoading, reload } = useAdminData(
    () => adminDeveloperApi.keys({ page, limit: LIMIT, search: query, status }),
    [page, query, status],
  );
  const [target, setTarget] = useState<AdminApiKeyRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const n = (value: number) => value.toLocaleString();

  return (
    <>
      <PageHeader title="Developer platform" description="API traffic, API keys and webhook health across all accounts." />
      <SuccessNote message={notice} />
      <ErrorNote message={statsError} />
      {statsLoading && !stats && <Loading />}
      {stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="API requests (24h)" value={n(stats.api_requests_24h)} />
            <StatCard label="API requests (30d)" value={n(stats.api_requests_30d)} />
            <StatCard label="API errors (24h)" value={n(stats.api_errors_24h)} tone={stats.api_errors_24h ? "warn" : undefined} />
            <StatCard
              label="Rate limited (24h)"
              value={n(stats.rate_limit_events_24h)}
              tone={stats.rate_limit_events_24h ? "warn" : undefined}
            />
            <StatCard label="Active keys" value={n(stats.active_keys)} hint={`${n(stats.revoked_keys)} revoked · ${n(stats.expired_keys)} expired`} />
            <StatCard label="Active webhooks" value={n(stats.active_webhooks)} />
            <StatCard
              label="Webhook failures (24h)"
              value={n(stats.webhook_failures_24h)}
              tone={stats.webhook_failures_24h ? "bad" : undefined}
            />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <Panel title="Top endpoints (30 days)" className="lg:col-span-1">
              <RankList items={stats.top_endpoints.map((e) => ({ key: e.endpoint, label: e.endpoint, value: e.requests, mono: true }))} />
            </Panel>
            <Panel title="Usage by organization (30 days)">
              <RankList items={stats.usage_by_organization.map((o) => ({ key: o.organization_id, label: o.name, value: o.requests }))} />
            </Panel>
            <Panel title="Usage by plan (30 days)">
              <RankList items={stats.usage_by_plan.map((p) => ({ key: p.plan, label: p.plan, value: p.requests }))} />
            </Panel>
          </div>
        </div>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold">API keys</h2>
      <ErrorNote message={keysError} />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQuery(search.trim());
        }}
      >
        <input
          aria-label="Search API keys"
          className={`${inputClass} min-w-56 flex-1`}
          placeholder="Search name, prefix, owner email or organization"
          value={search}
          maxLength={100}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select aria-label="Status" className={inputClass} value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          <option value="">All keys</option>
          <option value="active">Active</option>
          <option value="revoked">Revoked</option>
          <option value="expired">Expired</option>
        </select>
        <button type="submit" className={buttonClass}>
          Search
        </button>
      </form>
      {keysLoading && !keys && <Loading />}
      {keys && (
        <>
          <Table head={["Key", "Owner", "Scopes", "Status", "Last used", ""]} empty={keys.items.length === 0}>
            {keys.items.map((key) => (
              <tr key={key.id}>
                <td className="px-3 py-2">
                  <span className="block font-medium text-white">{key.name}</span>
                  <span className="font-mono text-xs text-muted">{key.key_prefix}…</span>
                </td>
                <td className="px-3 py-2">
                  <span className="block">{key.owner ?? "—"}</span>
                  <span className="text-xs text-muted">{key.owner_type === "organization" ? "Organization" : "User"}</span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex max-w-xs flex-wrap gap-1">
                    {key.scopes.map((scope) => (
                      <Badge key={scope} color="blue">
                        {scope}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <Badge color={STATUS_COLOR[key.status]}>{key.status}</Badge>
                </td>
                <td className="px-3 py-2 text-muted">{key.last_used_at ? formatDate(key.last_used_at) : "Never"}</td>
                <td className="px-3 py-2 text-right">
                  {key.status !== "revoked" && (
                    <button type="button" className={dangerButtonClass} onClick={() => setTarget(key)} aria-label={`Revoke ${key.name}`}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={keys.page} limit={keys.limit} total={keys.total} onPage={setPage} />
        </>
      )}

      <RevokeDialog
        target={target}
        onCancel={() => setTarget(null)}
        onDone={(row) => {
          setTarget(null);
          setNotice(`"${row.name}" (${row.key_prefix}…) was revoked. The action is in the audit log.`);
          reload();
          reloadStats();
        }}
      />
    </>
  );
}

function RankList({ items }: { items: { key: string; label: string; value: number; mono?: boolean }[] }) {
  if (items.length === 0) return <p className="text-sm text-muted">No data.</p>;
  return (
    <ol className="space-y-1 text-sm">
      {items.map((item) => (
        <li key={item.key} className="flex justify-between gap-2">
          <span className={`truncate ${item.mono ? "font-mono text-xs" : ""}`} title={item.label}>
            {item.label}
          </span>
          <span className="text-muted">{item.value.toLocaleString()}</span>
        </li>
      ))}
    </ol>
  );
}

function RevokeDialog({
  target,
  onCancel,
  onDone,
}: {
  target: AdminApiKeyRow | null;
  onCancel: () => void;
  onDone: (row: AdminApiKeyRow) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (target && !dialog.open) dialog.showModal();
    if (!target && dialog.open) dialog.close();
  }, [target]);

  async function confirm() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      const row = await adminDeveloperApi.revokeKey(target.id, reason.trim() || undefined);
      setReason("");
      onDone(row);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't revoke the key.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="revoke-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border border-border bg-surface-raised p-6 text-gray-100 backdrop:bg-black/70"
    >
      <h2 id="revoke-title" className="text-lg font-semibold">
        Revoke this API key?
      </h2>
      <p className="mt-2 text-sm text-muted">
        {target ? `${target.name} (${target.key_prefix}…) owned by ${target.owner ?? "unknown"}` : ""} stops working
        immediately. This can&apos;t be undone and is recorded in the audit log.
      </p>
      <label htmlFor="revoke-reason" className="mt-4 block text-sm text-muted">
        Reason (optional)
      </label>
      <input
        id="revoke-reason"
        className={`${inputClass} mt-1 w-full`}
        value={reason}
        maxLength={300}
        placeholder="e.g. Key published on GitHub"
        onChange={(e) => setReason(e.target.value)}
      />
      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          {error}
        </p>
      )}
      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <button type="button" onClick={onCancel} disabled={busy} className={buttonClass}>
          Cancel
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={busy}
          className="min-h-11 rounded-lg bg-rose-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-rose-500 disabled:opacity-60 md:min-h-0"
        >
          {busy ? "Revoking…" : "Revoke key"}
        </button>
      </div>
    </dialog>
  );
}
