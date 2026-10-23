"use client";

import Link from "next/link";

import { ErrorNote, HEALTH_LABELS, HealthBadge, Loading, PageHeader, Panel, buttonClass, useAdminData } from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

export default function AdminSystemPage() {
  const { data, error, loading, reload } = useAdminData(adminApi.systemHealth, []);

  return (
    <>
      <PageHeader title="System" description="Service status only; no addresses, keys or raw errors are shown.">
        <div className="flex gap-2">
          <button type="button" className={buttonClass} onClick={reload}>
            Refresh
          </button>
          <Link href="/admin/system/errors" className={buttonClass}>
            Error log
          </Link>
        </div>
      </PageHeader>
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <Panel>
          <p className="mb-4 text-sm">
            Overall: <HealthBadge status={data.status} /> <span className="ml-2 text-muted">version {data.version} · {data.environment}</span>
          </p>
          <ul className="divide-y divide-border">
            {data.services.map((s) => (
              <li key={s.name} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>{HEALTH_LABELS[s.name] ?? s.name}</span>
                <span className="flex items-center gap-2">
                  {s.detail && <span className="text-xs text-muted">{s.detail}</span>}
                  <HealthBadge status={s.status} />
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}
