"use client";

import { type FormEvent, useState } from "react";

import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  SuccessNote,
  Table,
  buttonClass,
  dangerButtonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { MAX_SUSPEND_REASON, parseFeaturedRank } from "@/lib/marketplace/admin";
import { REPORT_REASONS } from "@/lib/marketplace/display";
import { marketplaceApi } from "@/lib/marketplaceApi";
import type {
  AdminMarketplaceClone,
  AdminMarketplaceCloneStatus,
  AdminMarketplaceVisibilityUpdate,
  AdminReportRow,
  ReportStatus,
} from "@/types/marketplace";

const PAGE_SIZE = 20;
const REPORT_STATUSES: ReportStatus[] = ["open", "reviewing", "resolved", "dismissed"];
const CLONE_STATUSES: AdminMarketplaceCloneStatus[] = ["listed", "suspended", "featured", "all"];
const STATUS_COLOR: Record<ReportStatus, "red" | "amber" | "green" | "gray"> = {
  open: "red",
  reviewing: "amber",
  resolved: "green",
  dismissed: "gray",
};

type Tab = "reports" | "clones";

function reasonLabel(reason: string): string {
  return REPORT_REASONS.find((r) => r.value === reason)?.label ?? reason;
}

/** Marketplace moderation: reports, and which clones may appear in discovery. Every change is audited. */
export default function AdminMarketplacePage() {
  const [tab, setTab] = useState<Tab>("reports");
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cloneSearch, setCloneSearch] = useState("");

  async function run(action: () => Promise<unknown>, done: string, reload: () => void): Promise<boolean> {
    setActionError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      reload();
      return true;
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The action failed.");
      return false;
    }
  }

  return (
    <>
      <PageHeader
        title="Marketplace"
        description="Reports from visitors and users, and which clones may appear in discovery. Every change is written to the audit log."
      />
      <div role="tablist" className="mb-4 flex gap-2">
        {(["reports", "clones"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            className={`${buttonClass} ${tab === t ? "bg-accent/15" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "reports" ? "Reports" : "Clones"}
          </button>
        ))}
      </div>
      <SuccessNote message={notice} />
      <ErrorNote message={actionError} />
      {tab === "reports" ? (
        <ReportsTab
          run={run}
          onManageClone={(name) => {
            setCloneSearch(name);
            setTab("clones");
          }}
        />
      ) : (
        <ClonesTab run={run} initialSearch={cloneSearch} />
      )}
    </>
  );
}

type Run = (action: () => Promise<unknown>, done: string, reload: () => void) => Promise<boolean>;

// --- Reports ---------------------------------------------------------------------------

function ReportsTab({ run, onManageClone }: { run: Run; onManageClone: (cloneName: string) => void }) {
  const [status, setStatus] = useState<ReportStatus | "">("open");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminReportRow | null>(null);
  const reports = useAdminData(() => marketplaceApi.adminReports({ status, page, page_size: PAGE_SIZE }), [status, page]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2" role="group" aria-label="Filter reports by status">
        {(["", ...REPORT_STATUSES] as (ReportStatus | "")[]).map((s) => (
          <button
            key={s || "all"}
            type="button"
            aria-pressed={status === s}
            className={`${buttonClass} ${status === s ? "bg-accent/15" : ""}`}
            onClick={() => {
              setStatus(s);
              setPage(1);
            }}
          >
            {s || "All"}
          </button>
        ))}
      </div>
      <ErrorNote message={reports.error} />
      {reports.loading && !reports.data && <Loading />}
      {reports.data && (
        <>
          <Table head={["Clone", "Reason", "Reporter", "Status", "Reported", ""]} empty={reports.data.items.length === 0}>
            {reports.data.items.map((r) => (
              <tr key={r.id} className="align-top">
                <td className="px-3 py-2">
                  <a href={`/c/${r.clone.slug}`} target="_blank" rel="noopener noreferrer" className="block font-medium text-white hover:underline">
                    {r.clone.name}
                  </a>
                  <span className="text-xs text-muted">/c/{r.clone.slug}</span>
                </td>
                <td className="max-w-xs px-3 py-2">
                  <span className="block">{reasonLabel(r.reason)}</span>
                  {r.description && <span className="mt-1 block whitespace-pre-wrap break-words text-xs text-muted">{r.description}</span>}
                  {r.resolution_note && <span className="mt-1 block text-xs text-amber-200">Note: {r.resolution_note}</span>}
                </td>
                <td className="px-3 py-2 text-muted">{r.reporter}</td>
                <td className="px-3 py-2">
                  <Badge color={STATUS_COLOR[r.status]}>{r.status}</Badge>
                  {r.reviewed_at && <span className="block text-xs text-muted">{formatDate(r.reviewed_at)}</span>}
                </td>
                <td className="px-3 py-2 text-muted">{formatDate(r.created_at)}</td>
                <td className="space-x-2 whitespace-nowrap px-3 py-2 text-right">
                  <button type="button" className={buttonClass} onClick={() => setEditing(r)}>
                    Review
                  </button>
                  <button type="button" className={buttonClass} onClick={() => onManageClone(r.clone.name)}>
                    Manage clone
                  </button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={reports.data.page} limit={reports.data.page_size} total={reports.data.total} onPage={setPage} />
        </>
      )}
      {editing && (
        <ReviewPanel
          key={editing.id}
          report={editing}
          onClose={() => setEditing(null)}
          onSave={async (next, note) => {
            const ok = await run(() => marketplaceApi.adminUpdateReport(editing.id, next, note), `Report marked ${next}.`, reports.reload);
            if (ok) setEditing(null);
          }}
        />
      )}
    </>
  );
}

function ReviewPanel({
  report,
  onClose,
  onSave,
}: {
  report: AdminReportRow;
  onClose: () => void;
  onSave: (status: ReportStatus, note: string) => Promise<void>;
}) {
  const [status, setStatus] = useState<ReportStatus>(report.status === "open" ? "reviewing" : report.status);
  const [note, setNote] = useState(report.resolution_note ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await onSave(status, note);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`Review report: ${report.clone.name}`} className="mt-6">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[12rem_1fr_auto_auto] sm:items-end">
        <label className="text-sm">
          <span className="text-muted">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as ReportStatus)} className={`${inputClass} mt-1 w-full`}>
            {REPORT_STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="text-muted">Resolution note (internal, max 500)</span>
          <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} className={`${inputClass} mt-1 w-full`} />
        </label>
        <button type="submit" disabled={busy} className={buttonClass}>Save</button>
        <button type="button" onClick={onClose} className={buttonClass}>Close</button>
      </form>
    </Panel>
  );
}

// --- Clones ----------------------------------------------------------------------------

function ClonesTab({ run, initialSearch }: { run: Run; initialSearch: string }) {
  const [status, setStatus] = useState<AdminMarketplaceCloneStatus>(initialSearch ? "all" : "listed");
  const [draft, setDraft] = useState(initialSearch);
  const [q, setQ] = useState(initialSearch);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminMarketplaceClone | null>(null);
  const clones = useAdminData(() => marketplaceApi.adminClones({ status, q, page, page_size: PAGE_SIZE }), [status, q, page]);

  async function change(clone: AdminMarketplaceClone, update: AdminMarketplaceVisibilityUpdate, done: string) {
    const ok = await run(() => marketplaceApi.adminSetVisibility(clone.id, update), done, clones.reload);
    if (ok) setEditing(null);
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter clones">
          {CLONE_STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={status === s}
              className={`${buttonClass} ${status === s ? "bg-accent/15" : ""}`}
              onClick={() => {
                setStatus(s);
                setPage(1);
              }}
            >
              {s}
            </button>
          ))}
        </div>
        <form
          role="search"
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setQ(draft.trim());
            setPage(1);
          }}
        >
          <label className="sr-only" htmlFor="admin-mp-search">Search clones</label>
          <input id="admin-mp-search" type="search" maxLength={100} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Name or slug" className={inputClass} />
          <button type="submit" className={buttonClass}>Search</button>
        </form>
      </div>
      <ErrorNote message={clones.error} />
      {clones.loading && !clones.data && <Loading />}
      {clones.data && (
        <>
          <Table head={["Clone", "Marketplace", "Featured", "Published", "Open reports", ""]} empty={clones.data.items.length === 0}>
            {clones.data.items.map((c) => (
              <tr key={c.id} className="align-top">
                <td className="px-3 py-2">
                  <a href={`/c/${c.slug}`} target="_blank" rel="noopener noreferrer" className="block font-medium text-white hover:underline">
                    {c.name}
                  </a>
                  <span className="text-xs text-muted">/c/{c.slug}</span>
                </td>
                <td className="px-3 py-2">
                  {c.suspended ? (
                    <Badge color="red">suspended</Badge>
                  ) : c.listed ? (
                    <Badge color="green">listed</Badge>
                  ) : (
                    <Badge color="gray">{c.marketplace_enabled ? "enabled, not listed" : "opted out"}</Badge>
                  )}
                  {c.suspended && c.suspended_reason && <span className="mt-1 block max-w-xs text-xs text-muted">{c.suspended_reason}</span>}
                </td>
                <td className="px-3 py-2 text-muted">{c.featured_rank ?? "—"}</td>
                <td className="px-3 py-2 text-muted">{formatDate(c.published_at)}</td>
                <td className="px-3 py-2">{c.open_reports > 0 ? <Badge color="amber">{c.open_reports}</Badge> : <span className="text-muted">0</span>}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  <button type="button" className={buttonClass} onClick={() => setEditing(c)}>
                    Manage
                  </button>
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={clones.data.page} limit={clones.data.page_size} total={clones.data.total} onPage={setPage} />
        </>
      )}
      {editing && <ClonePanel key={editing.id} clone={editing} onClose={() => setEditing(null)} onChange={(u, done) => change(editing, u, done)} />}
    </>
  );
}

function ClonePanel({
  clone,
  onClose,
  onChange,
}: {
  clone: AdminMarketplaceClone;
  onClose: () => void;
  onChange: (update: AdminMarketplaceVisibilityUpdate, done: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [rank, setRank] = useState(clone.featured_rank === null ? "" : String(clone.featured_rank));
  const [busy, setBusy] = useState(false);
  const parsedRank = parseFeaturedRank(rank);

  async function busyWhile(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title={`Manage: ${clone.name}`} className="mt-6">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        {clone.suspended ? (
          <>
            <p className="text-sm text-muted">Suspended{clone.suspended_reason ? `: ${clone.suspended_reason}` : ""}. Lifting it lets the clone appear again if the owner still has it published.</p>
            <button type="button" disabled={busy} className={buttonClass} onClick={() => void busyWhile(() => onChange({ suspended: false }, `${clone.name} may be listed again.`))}>
              Unsuspend
            </button>
          </>
        ) : (
          <>
            <label className="text-sm">
              <span className="text-muted">Suspension reason (internal, max {MAX_SUSPEND_REASON})</span>
              <input value={reason} maxLength={MAX_SUSPEND_REASON} onChange={(e) => setReason(e.target.value)} className={`${inputClass} mt-1 w-full`} />
            </label>
            <button
              type="button"
              disabled={busy}
              className={dangerButtonClass}
              onClick={() => void busyWhile(() => onChange({ suspended: true, reason }, `${clone.name} is suspended from the marketplace.`))}
            >
              Suspend from marketplace
            </button>
          </>
        )}
      </div>

      <form
        className="mt-4 grid gap-3 border-t border-border pt-4 sm:grid-cols-[12rem_auto_auto] sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          if (parsedRank === undefined) return;
          void busyWhile(() =>
            onChange(
              { featured_rank: parsedRank },
              parsedRank === null ? `${clone.name} is no longer featured.` : `${clone.name} is featured at rank ${parsedRank}.`,
            ),
          );
        }}
      >
        <label className="text-sm">
          <span className="text-muted">Featured rank (0–1000, lower first)</span>
          <input
            value={rank}
            inputMode="numeric"
            onChange={(e) => setRank(e.target.value)}
            aria-invalid={parsedRank === undefined}
            placeholder="Not featured"
            className={`${inputClass} mt-1 w-full`}
          />
        </label>
        <button type="submit" disabled={busy || parsedRank === undefined} className={buttonClass}>
          {parsedRank === null ? "Clear featured" : "Set featured rank"}
        </button>
        <button type="button" onClick={onClose} className={buttonClass}>Close</button>
      </form>
      {parsedRank === undefined && <p className="mt-1 text-xs text-rose-300" role="alert">Use a whole number from 0 to 1000, or leave empty.</p>}
    </Panel>
  );
}
