"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorNote, Loading, PageHeader, Panel, StatCard, useAdminData } from "@/components/admin/ui";
import { OwnerSelect, useOrganizations } from "@/components/developer/ui";
import { developerApi } from "@/lib/developerApi";

export default function DeveloperOverviewPage() {
  const orgs = useOrganizations();
  const [owner, setOwner] = useState("");
  const { data, error, loading } = useAdminData(() => developerApi.overview(owner || undefined), [owner]);
  const n = (value: number) => value.toLocaleString();
  const share = data && data.monthly_limit > 0 ? Math.min(100, (data.monthly_requests / data.monthly_limit) * 100) : 0;

  return (
    <>
      <PageHeader title="Developer" description="Use your AI Clones from your own apps with the developer API.">
        <OwnerSelect orgs={orgs} value={owner} onChange={setOwner} />
      </PageHeader>
      <ErrorNote message={error} />
      {loading && !data && <Loading />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="API requests" value={n(data.api_requests_30d)} hint="Last 30 days" />
            <StatCard label="Chat requests" value={n(data.chat_requests_30d)} hint="Last 30 days" />
            <StatCard label="Successful" value={n(data.successful_requests_30d)} hint="Last 30 days" />
            <StatCard
              label="Failed"
              value={n(data.failed_requests_30d)}
              hint="Last 30 days"
              tone={data.failed_requests_30d > 0 ? "warn" : undefined}
            />
            <StatCard label="Rate limit" value={`${n(data.rate_limit_per_minute)}/min`} hint={`Plan: ${data.plan}`} />
            <StatCard
              label="This month"
              value={n(data.monthly_requests)}
              hint={data.monthly_limit > 0 ? `of ${n(data.monthly_limit)} requests` : "No monthly limit"}
              tone={share >= 100 ? "bad" : share >= 80 ? "warn" : undefined}
            />
            <StatCard label="Active keys" value={n(data.active_keys)} />
            <StatCard label="Active webhooks" value={n(data.active_webhooks)} />
          </div>

          {data.monthly_limit > 0 && (
            <Panel title="Monthly usage">
              <div
                role="progressbar"
                aria-label="Monthly API requests used"
                aria-valuemin={0}
                aria-valuemax={data.monthly_limit}
                aria-valuenow={data.monthly_requests}
                className="h-3 w-full overflow-hidden rounded-full bg-surface"
              >
                <div
                  className={`h-full rounded-full ${share >= 100 ? "bg-rose-500" : share >= 80 ? "bg-amber-400" : "bg-accent"}`}
                  style={{ width: `${share}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-muted">
                {n(data.monthly_requests)} of {n(data.monthly_limit)} requests used this month ({Math.round(share)}%).
              </p>
            </Panel>
          )}

          <Panel title="Get started">
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
              <li>
                <Link href="/developer/keys" className="text-accent-soft hover:underline">
                  Create an API key
                </Link>{" "}
                with only the scopes your app needs.
              </li>
              <li>
                Call the API with <code className="font-mono text-white">Authorization: Bearer ahc_live_…</code> —{" "}
                <Link href="/developer/docs" className="text-accent-soft hover:underline">
                  see the docs
                </Link>
                .
              </li>
              <li>
                <Link href="/developer/webhooks" className="text-accent-soft hover:underline">
                  Add a webhook
                </Link>{" "}
                to hear about new conversations, finished videos and more.
              </li>
            </ol>
          </Panel>
        </div>
      )}
    </>
  );
}
