"use client";

import { useState } from "react";

import {
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  SeverityBadge,
  Table,
  buttonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { adminApi } from "@/lib/adminApi";

const LIMIT = 20;
const EVENT_TYPES = [
  "LOGIN_FAILED",
  "LOGIN_SUCCESS",
  "LOGIN_LOCKED",
  "LOGIN_DISABLED_ACCOUNT",
  "UNAUTHORIZED_ACCESS",
  "ADMIN_ACCESS_DENIED",
  "RATE_LIMIT_EXCEEDED",
  "PUBLIC_ABUSE_DETECTED",
  "INVALID_TOKEN",
  "SUSPICIOUS_REQUEST",
];

function details(value: Record<string, unknown>): string {
  return Object.entries(value)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ");
}

export default function AdminSecurityPage() {
  const [tab, setTab] = useState<"events" | "audit">("events");
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState("");
  const [severity, setSeverity] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const events = useAdminData(
    () =>
      tab === "events"
        ? adminApi.securityEvents({ page, limit: LIMIT, event_type: eventType, severity, date_from: dateFrom, date_to: dateTo })
        : Promise.resolve(null),
    [tab, page, eventType, severity, dateFrom, dateTo],
  );
  const audit = useAdminData(
    () => (tab === "audit" ? adminApi.auditLogs({ page, limit: LIMIT, date_from: dateFrom, date_to: dateTo }) : Promise.resolve(null)),
    [tab, page, dateFrom, dateTo],
  );
  const current = tab === "events" ? events : audit;

  return (
    <>
      <PageHeader
        title="Security"
        description="Security events (kept for SECURITY_LOG_RETENTION_DAYS) and the admin audit log. No passwords, tokens or message text are stored."
      />
      <div role="tablist" className="mb-4 flex gap-2">
        {(["events", "audit"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            className={`${buttonClass} ${tab === t ? "bg-accent/15" : ""}`}
            onClick={() => { setTab(t); setPage(1); }}
          >
            {t === "events" ? "Security events" : "Admin audit log"}
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {tab === "events" && (
          <>
            <select aria-label="Event type" className={inputClass} value={eventType} onChange={(e) => { setPage(1); setEventType(e.target.value); }}>
              <option value="">All events</option>
              {EVENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select aria-label="Severity" className={inputClass} value={severity} onChange={(e) => { setPage(1); setSeverity(e.target.value); }}>
              <option value="">Any severity</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </>
        )}
        <input aria-label="From date" type="date" className={inputClass} value={dateFrom} onChange={(e) => { setPage(1); setDateFrom(e.target.value); }} />
        <input aria-label="To date" type="date" className={inputClass} value={dateTo} onChange={(e) => { setPage(1); setDateTo(e.target.value); }} />
      </div>
      <ErrorNote message={current.error} />
      {current.loading && !current.data && <Loading />}

      {tab === "events" && events.data && (
        <>
          <Table head={["When", "Event", "Severity", "User", "Address", "Details"]} empty={events.data.items.length === 0}>
            {events.data.items.map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{formatDate(e.created_at)}</td>
                <td className="px-3 py-2 font-mono text-xs text-white">{e.event_type}</td>
                <td className="px-3 py-2"><SeverityBadge severity={e.severity} /></td>
                <td className="px-3 py-2 font-mono text-xs text-muted">{e.user_id ? e.user_id.slice(0, 8) : "—"}</td>
                <td className="px-3 py-2 text-muted">{e.ip_address ?? "—"}</td>
                <td className="max-w-xs truncate px-3 py-2 text-xs text-muted" title={details(e.details)}>{details(e.details)}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={events.data.page} limit={events.data.limit} total={events.data.total} onPage={setPage} />
        </>
      )}

      {tab === "audit" && audit.data && (
        <>
          <Table head={["When", "Admin", "Action", "Target", "Details"]} empty={audit.data.items.length === 0}>
            {audit.data.items.map((a) => (
              <tr key={a.id}>
                <td className="whitespace-nowrap px-3 py-2 text-muted">{formatDate(a.created_at)}</td>
                <td className="px-3 py-2">{a.admin_email ?? a.admin_user_id.slice(0, 8)}</td>
                <td className="px-3 py-2 font-mono text-xs text-white">{a.action}</td>
                <td className="px-3 py-2 text-xs text-muted">
                  {a.target_type}
                  {a.target_id ? ` ${a.target_id.slice(0, 8)}` : ""}
                </td>
                <td className="max-w-xs truncate px-3 py-2 text-xs text-muted" title={details(a.details)}>{details(a.details)}</td>
              </tr>
            ))}
          </Table>
          <Pagination page={audit.data.page} limit={audit.data.limit} total={audit.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
