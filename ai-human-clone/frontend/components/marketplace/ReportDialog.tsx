"use client";

import { useEffect, useId, useRef, useState } from "react";

import { MAX_REPORT_DESCRIPTION, REPORT_REASONS, marketplaceErrorMessage } from "@/lib/marketplace/display";
import { type MarketplaceError, marketplaceApi } from "@/lib/marketplaceApi";
import type { ReportReason } from "@/types/marketplace";

type Step = "form" | "confirm" | "done";

/** "Report this AI Clone": pick a reason, optionally describe, confirm, send. Login not required. */
export function ReportButton({ slug, cloneName }: { slug: string; cloneName: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex min-h-12 items-center justify-center gap-2 rounded-xl border border-border px-5 text-sm text-muted hover:border-rose-400/60 hover:text-rose-200 sm:min-h-11"
      >
        <span aria-hidden>⚑</span> Report
      </button>
      {open && <ReportDialog slug={slug} cloneName={cloneName} onClose={() => setOpen(false)} />}
    </>
  );
}

function ReportDialog({ slug, cloneName, onClose }: { slug: string; cloneName: string; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [step, setStep] = useState<Step>("form");
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  async function submit() {
    if (!reason) return;
    setBusy(true);
    setError(null);
    try {
      await marketplaceApi.report(slug, reason, description);
      setStep("done");
    } catch (err) {
      setError(marketplaceErrorMessage(err as MarketplaceError));
      setStep("form");
    } finally {
      setBusy(false);
    }
  }

  const reasonLabel = REPORT_REASONS.find((r) => r.value === reason)?.label;

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-border bg-surface-raised p-0 text-gray-100 backdrop:bg-black/60"
    >
      <div className="p-5 sm:p-6">
        <h2 id={titleId} className="text-lg font-semibold">
          Report {cloneName}
        </h2>
        {step === "done" ? (
          <>
            <p className="mt-3 text-sm text-gray-200" role="status">
              Thank you. Your report was sent to the moderators. They review every report; nothing changes for the clone until they do.
            </p>
            <div className="mt-6 flex justify-end">
              <button type="button" onClick={() => ref.current?.close()} className="min-h-11 rounded-xl bg-accent px-5 text-sm font-medium text-white">
                Close
              </button>
            </div>
          </>
        ) : step === "confirm" ? (
          <>
            <p className="mt-3 text-sm text-gray-200">Send this report to the moderators?</p>
            <p className="mt-2 text-sm text-muted">Reason: {reasonLabel}</p>
            {description.trim() && <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted">“{description.trim()}”</p>}
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setStep("form")} disabled={busy} className="min-h-11 rounded-xl border border-border px-5 text-sm">
                Back
              </button>
              <button type="button" onClick={submit} disabled={busy} className="min-h-11 rounded-xl bg-rose-500 px-5 text-sm font-medium text-white hover:bg-rose-500/90 disabled:opacity-50">
                {busy ? "Sending…" : "Send report"}
              </button>
            </div>
          </>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (reason) setStep("confirm");
            }}
          >
            <fieldset className="mt-4">
              <legend className="text-sm text-muted">What is wrong?</legend>
              <div className="mt-2 space-y-1">
                {REPORT_REASONS.map((option) => (
                  <label key={option.value} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 text-sm hover:bg-white/5">
                    <input
                      type="radio"
                      name="reason"
                      value={option.value}
                      checked={reason === option.value}
                      onChange={() => setReason(option.value)}
                      className="h-4 w-4 accent-accent"
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="mt-4 block text-sm text-muted" htmlFor={`${titleId}-details`}>
              Details (optional)
            </label>
            <textarea
              id={`${titleId}-details`}
              value={description}
              maxLength={MAX_REPORT_DESCRIPTION}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-gray-100"
            />
            <p className="mt-1 text-right text-xs text-muted">
              {description.length}/{MAX_REPORT_DESCRIPTION}
            </p>
            {error && (
              <p className="mt-2 text-sm text-rose-300" role="alert">
                {error}
              </p>
            )}
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => ref.current?.close()} className="min-h-11 rounded-xl border border-border px-5 text-sm">
                Cancel
              </button>
              <button type="submit" disabled={!reason} className="min-h-11 rounded-xl bg-accent px-5 text-sm font-medium text-white disabled:opacity-50">
                Continue
              </button>
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
