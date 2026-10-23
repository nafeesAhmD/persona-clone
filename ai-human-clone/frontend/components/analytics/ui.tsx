"use client";

// Small mobile-first building blocks shared by the analytics, billing and organization pages.
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";

/** Touch-friendly controls: every one is at least 44px tall. */
export const btnPrimary =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50";
export const btnSecondary =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-border px-4 text-sm text-white hover:border-accent hover:bg-surface-raised disabled:cursor-not-allowed disabled:opacity-50";
export const btnDanger =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-rose-500/50 px-4 text-sm text-rose-200 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50";
export const inputCls =
  "min-h-11 w-full min-w-0 rounded-xl border border-border bg-surface px-3 text-base text-white placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm";
export const labelCls = "mb-1 block text-sm font-medium text-gray-200";

/** Page frame: side gutters, room for the mobile bottom navigation, no horizontal scroll. */
export function PageShell({
  title,
  description,
  back,
  actions,
  busy = false,
  children,
}: {
  /** Marks the page as submitting so a PWA update never reloads mid-action. */
  busy?: boolean;
  title: string;
  description?: React.ReactNode;
  back?: { href: string; label: string };
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <main data-busy={busy ? "true" : undefined} className="mx-auto w-full max-w-4xl overflow-x-hidden px-4 pt-4 pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:pt-8 md:pb-0">
      <div className="md:pb-12">
        {back && (
          <Link href={back.href} className="mb-2 inline-flex min-h-11 items-center text-sm text-accent-soft hover:underline">
            <span aria-hidden="true">←&nbsp;</span>
            {back.label}
          </Link>
        )}
        <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h1 className="break-words text-2xl font-semibold tracking-tight">{title}</h1>
            {description && <div className="mt-1 text-sm text-muted">{description}</div>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
        {children}
      </div>
    </main>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-border bg-surface-raised/60 p-4 ${className}`}>{children}</div>;
}

/** A section that can be folded away on small screens (native <details>: keyboard and screen-reader friendly). */
export function Collapsible({
  title,
  defaultOpen = true,
  children,
  meta,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <details open={defaultOpen} className="group rounded-2xl border border-border bg-surface-raised/40">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 text-sm font-semibold text-white [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">{title}</span>
        <span className="flex shrink-0 items-center gap-2 text-xs font-normal text-muted">
          {meta}
          <span aria-hidden="true" className="transition-transform group-open:rotate-180">
            ▾
          </span>
        </span>
      </summary>
      <div className="border-t border-border px-4 py-4">{children}</div>
    </details>
  );
}

/** Notice for results of an action; read out by screen readers. */
export function Notice({ tone, children }: { tone: "error" | "success" | "info"; children: React.ReactNode }) {
  const cls =
    tone === "error"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-200"
      : tone === "success"
        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
        : "border-border bg-surface-raised text-gray-200";
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-xl border px-4 py-3 text-sm ${cls}`}>
      {children}
    </div>
  );
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3 py-4">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((i) => (
        <div key={i} aria-hidden="true" className="h-20 animate-pulse rounded-2xl bg-surface-raised/70" />
      ))}
    </div>
  );
}

export function EmptyState({ title, body, children }: { title: string; body?: string; children?: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-border px-4 py-10 text-center">
      <p className="font-medium text-white">{title}</p>
      {body && <p className="mx-auto mt-1 max-w-sm text-sm text-muted">{body}</p>}
      {children && <div className="mt-4 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * Load data and keep the raw error (so ApiErrorState can tell offline / 403 / 404 apart).
 * Loads again when `key` changes or on reload().
 */
export function useApiData<T>(load: () => Promise<T>, key: string) {
  const [state, setState] = useState<{ data: T | null; error: unknown; loading: boolean; key: string | null }>({
    data: null,
    error: null,
    loading: true,
    key: null,
  });
  const [version, setVersion] = useState(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    let cancelled = false;
    loadRef
      .current()
      .then((data) => !cancelled && setState({ data, error: null, loading: false, key }))
      .catch((error: unknown) => !cancelled && setState((s) => ({ data: s.data, error, loading: false, key })));
    return () => {
      cancelled = true;
    };
  }, [key, version]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    setVersion((v) => v + 1);
  }, []);
  // While a new key loads, the old data stays visible but is marked as loading.
  const loading = state.loading || state.key !== key;
  return { data: state.data, error: state.error, loading, reload, setData: (data: T) => setState((s) => ({ ...s, data })) };
}

/**
 * A dialog that is a bottom sheet on phones and a centered dialog on larger screens.
 * Built on <dialog> so focus trapping and Escape work natively.
 */
export function Sheet({
  open,
  title,
  onClose,
  children,
  busy = false,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      data-busy={busy ? "true" : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="fixed inset-x-0 bottom-0 top-auto m-0 max-h-[90dvh] w-full max-w-none overflow-y-auto rounded-t-2xl border border-border bg-surface-raised p-0 text-gray-100 backdrop:bg-black/70 sm:inset-0 sm:m-auto sm:max-w-md sm:rounded-2xl"
    >
      <div className="px-4 pt-3 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:p-6">
        <div aria-hidden="true" className="mx-auto mb-3 h-1 w-10 rounded-full bg-border sm:hidden" />
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl text-muted hover:bg-surface hover:text-white"
            aria-label="Close"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

/** A labelled progress bar; the numbers are always written out too (never color alone). */
export function UsageMeter({
  label,
  percent,
  text,
  tone,
  toneText,
}: {
  label: string;
  percent: number | null;
  text: string;
  tone: "ok" | "warn" | "over" | "unlimited";
  toneText?: string | null;
}) {
  const fill = tone === "over" ? "bg-rose-500" : tone === "warn" ? "bg-amber-400" : "bg-accent";
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium text-white">{label}</span>
        <span className="text-sm text-gray-200">{text}</span>
      </div>
      {percent !== null ? (
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${text}${toneText ? `, ${toneText}` : ""}`}
          className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-surface"
        >
          <div className={`h-full rounded-full ${fill}`} style={{ width: `${percent}%` }} />
        </div>
      ) : (
        <p className="mt-1 text-xs text-muted">No limit on your plan.</p>
      )}
      {toneText && (
        <p className={`mt-1 text-xs font-medium ${tone === "over" ? "text-rose-300" : "text-amber-300"}`}>
          <span aria-hidden="true">{tone === "over" ? "⛔ " : "⚠ "}</span>
          {toneText}
        </p>
      )}
    </div>
  );
}
