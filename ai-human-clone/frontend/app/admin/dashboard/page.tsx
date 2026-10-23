"use client";

import Link from "next/link";

import { ErrorNote, HEALTH_LABELS, HealthBadge, Loading, PageHeader, Panel, StatCard, useAdminData } from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

export default function AdminDashboardPage() {
  const { data, error, loading } = useAdminData(adminApi.dashboard, []);

  return (
    <>
      <PageHeader title="Admin Dashboard" description="Platform overview. Counts only; no private content." />
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-6">
          {data.maintenance_mode && (
            <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              Maintenance mode is on. Only administrators can use the app.{" "}
              <Link href="/admin/settings" className="underline">
                Settings
              </Link>
            </p>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="Users" value={data.total_users} hint={`${data.active_users} active · ${data.admin_users} admin`} />
            <StatCard label="Disabled users" value={data.disabled_users} tone={data.disabled_users ? "warn" : undefined} />
            <StatCard label="AI Clones" value={data.total_clones} hint={`${data.disabled_clones} disabled`} />
            <StatCard
              label="Public / Unlisted"
              value={`${data.public_clones} / ${data.unlisted_clones}`}
              hint={`${data.private_clones} private`}
            />
            <StatCard label="Documents" value={data.total_documents} />
            <StatCard label="Memories" value={data.total_memories} />
            <StatCard label="Conversations" value={data.total_conversations} hint={`${data.total_messages} messages`} />
            <StatCard label="Visitor sessions" value={data.public_sessions} />
            <StatCard label="Security events (24h)" value={data.security_events_24h} tone={data.security_events_24h ? "warn" : undefined} />
            <StatCard label="Errors (24h)" value={data.errors_24h} tone={data.errors_24h ? "bad" : undefined} />
            <StatCard label="Usage events (24h)" value={data.usage_events_24h} />
          </div>
          <Panel title="Service health">
            <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {data.health.map((item) => (
                <li key={item.name} className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-sm">
                  <span>{HEALTH_LABELS[item.name] ?? item.name}</span>
                  <HealthBadge status={item.status} />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      )}
    </>
  );
}
