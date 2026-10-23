"use client";

import { useEffect, useId, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Modal confirmation built on <dialog>, so focus trapping and Escape work natively.
 * Phones: a full-width bottom sheet with big buttons; sm and up: a centered card.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  busyLabel = "Working…",
  busy = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const messageId = useId();

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
      aria-describedby={messageId}
      onCancel={(event) => {
        event.preventDefault(); // Escape: go through onCancel so state stays in sync
        if (!busy) onCancel();
      }}
      className="mx-0 mb-0 mt-auto max-h-[90dvh] w-full max-w-none overflow-y-auto rounded-t-2xl border border-border bg-surface-raised p-6 pb-[calc(1.5rem+env(safe-area-inset-bottom))] text-gray-100 backdrop:bg-black/70 sm:m-auto sm:w-[calc(100%-2rem)] sm:max-w-md sm:rounded-2xl sm:pb-6"
    >
      <h2 id={titleId} className="text-lg font-semibold">{title}</h2>
      <p id={messageId} className="mt-2 text-sm text-muted">{message}</p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-rose-300">
          <span aria-hidden="true">⚠ </span>
          {error}
        </p>
      )}
      <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="min-h-12 rounded-xl border border-border px-4 py-2.5 text-sm hover:border-accent disabled:opacity-50 sm:min-h-11"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="min-h-12 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-rose-500 disabled:cursor-wait disabled:opacity-60 sm:min-h-11"
        >
          {busy ? busyLabel : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
