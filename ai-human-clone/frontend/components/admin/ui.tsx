"use client";

import { Children, cloneElement, isValidElement, useCallback, useEffect, useState } from "react";

import type { HealthStatus } from "@/types/admin";

/** Load data with loading/error state; it loads again when `deps` change or on `reload()`. */
export function useAdminData<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const key = JSON.stringify(deps);

  useEffect(() => {
    let cancelled = false;
    load()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : "Couldn't load data."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // `load` is a new function on every render; `key` captures what it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, loading, reload };
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export function Panel({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-border bg-surface-raised/60 p-4 sm:p-5 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold text-white">{title}</h2>}
      {children}
    </section>
  );
}

export function StatCard({ label, value, hint, tone }: { label: string; value: number | string; hint?: string; tone?: "warn" | "bad" }) {
  const color = tone === "bad" ? "text-rose-300" : tone === "warn" ? "text-amber-300" : "text-white";
  return (
    <div className="rounded-2xl border border-border bg-surface-raised/60 p-4">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${color}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

const BADGE: Record<string, string> = {
  green: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  red: "border-rose-500/30 bg-rose-500/10 text-rose-200",
  amber: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  gray: "border-border bg-surface text-muted",
  blue: "border-accent/30 bg-accent/10 text-accent-soft",
};

export function Badge({ children, color = "gray" }: { children: React.ReactNode; color?: keyof typeof BADGE }) {
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${BADGE[color]}`}>{children}</span>;
}

/** Readable names for the services in system health. */
export const HEALTH_LABELS: Record<string, string> = {
  application: "Application",
  database: "Database (PostgreSQL)",
  qdrant: "Vector store (Qdrant)",
  embeddings: "Embedding model",
  storage: "File storage",
  llm: "Language model",
  stt: "Speech-to-text",
  tts: "Text-to-speech",
  lipsync: "Lip-sync (avatar videos)",
};

export function HealthBadge({ status }: { status: HealthStatus }) {
  const color = status === "healthy" ? "green" : status === "unavailable" ? "red" : status === "degraded" ? "amber" : "gray";
  return <Badge color={color}>{status.replace("_", " ")}</Badge>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const color = severity === "high" ? "red" : severity === "medium" ? "amber" : "gray";
  return <Badge color={color}>{severity}</Badge>;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      {message}
    </p>
  );
}

export function SuccessNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="status" className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
      {message}
    </p>
  );
}

export function Pagination({ page, limit, total, onPage }: { page: number; limit: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <nav aria-label="Pages" className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
      <span>
        {total === 0 ? "No results" : `${(page - 1) * limit + 1}–${Math.min(page * limit, total)} of ${total}`}
      </span>
      <div className="flex gap-2">
        <button type="button" className={buttonClass} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <button type="button" className={buttonClass} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </div>
    </nav>
  );
}

export const buttonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-border px-3 py-1.5 text-sm text-white hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-40 md:min-h-0";
export const dangerButtonClass =
  "inline-flex min-h-11 items-center justify-center rounded-lg border border-rose-500/40 px-3 py-1.5 text-sm text-rose-200 hover:bg-rose-500/10 disabled:opacity-40 md:min-h-0";
export const inputClass =
  "min-h-11 max-w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-white placeholder:text-muted outline-none! focus:border-accent md:min-h-0";

type CellProps = { "data-label"?: string; children?: React.ReactNode };

/** Give every <td> of every row its column name (data-label), used by the stacked phone layout. */
function labelCells(children: React.ReactNode, head: string[]): React.ReactNode {
  return Children.map(children, (row) => {
    if (!isValidElement<{ children?: React.ReactNode }>(row) || row.type !== "tr") return row;
    let index = 0;
    const cells = Children.map(row.props.children, (cell) => {
      if (!isValidElement<CellProps>(cell) || (cell.type !== "td" && cell.type !== "th")) return cell;
      const label = head[index] ?? "";
      index += 1;
      return cell.props["data-label"] !== undefined ? cell : cloneElement(cell, { "data-label": label });
    });
    return cloneElement(row, undefined, cells);
  });
}

/**
 * Data table. md and up: a normal table (scrolls inside its box if wide). Below md:
 * each row is a stacked card with "column: value" lines, so nothing is tiny or
 * scrolls sideways. Same API as before: pass <tr><td/>…</tr> rows as children.
 */
export function Table({ head, children, empty }: { head: string[]; children: React.ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-border">
      <table className="rtable w-full text-left text-sm md:min-w-[640px]">
        <thead className="bg-surface-raised text-xs uppercase tracking-wide text-muted">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {empty ? (
            <tr>
              <td colSpan={head.length} className="px-3 py-8 text-center text-muted">
                Nothing here yet.
              </td>
            </tr>
          ) : (
            labelCells(children, head)
          )}
        </tbody>
      </table>
    </div>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function Loading() {
  return <p className="py-10 text-center text-sm text-muted">Loading…</p>;
}
