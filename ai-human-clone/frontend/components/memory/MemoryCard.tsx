"use client";

import { useState } from "react";

import { inputClass } from "@/components/FormField";
import { MEMORY_MAX_CHARACTERS, MEMORY_TYPES, formatConfidence, formatDate, memoryTypeLabel, sourceText } from "@/lib/memory";
import { cn } from "@/lib/utils";
import type { CloneMemory, MemoryStatus, MemoryType, MemoryUpdatePayload } from "@/types/memory";

export type MemoryAction = "approve" | "reject" | "archive" | "delete";

interface MemoryCardProps {
  memory: CloneMemory;
  /** Resolves when done; a rejection's message is shown on the card. */
  onAction: (memory: CloneMemory, action: MemoryAction) => Promise<void>;
  onSave: (memory: CloneMemory, update: MemoryUpdatePayload) => Promise<void>;
  /** Private / Public switch (memory page only). */
  onVisibility?: (memory: CloneMemory, visibility: "private" | "public") => Promise<void>;
  compact?: boolean;
}

const STATUS_STYLES: Record<MemoryStatus, string> = {
  approved: "border-emerald-500/40 text-emerald-300",
  candidate: "border-amber-400/40 text-amber-300",
  rejected: "border-rose-500/40 text-rose-300",
  archived: "border-border text-muted",
};

const STATUS_ICONS: Record<MemoryStatus, string> = {
  approved: "✓",
  candidate: "⏳",
  rejected: "✕",
  archived: "▢",
};

const STATUS_LABELS: Record<MemoryStatus, string> = {
  approved: "Approved",
  candidate: "Pending review",
  rejected: "Rejected",
  archived: "Archived",
};

// At least 44px tall on touch screens.
const buttonClass = "inline-flex min-h-11 items-center justify-center rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50 md:min-h-0";

export function MemoryCard({ memory, onAction, onSave, onVisibility, compact = false }: MemoryCardProps) {
  const [editing, setEditing] = useState(false);
  const [type, setType] = useState<MemoryType>(memory.memory_type);
  const [content, setContent] = useState(memory.content);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isCandidate = memory.status === "candidate";

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await work();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusy(null);
    }
  }

  function startEditing() {
    setType(memory.memory_type);
    setContent(memory.content);
    setError(null);
    setEditing(true);
  }

  async function save(approveToo: boolean) {
    const text = content.trim();
    if (!text) {
      setError("The memory can't be empty.");
      return;
    }
    const update: MemoryUpdatePayload = { memory_type: type, content: text };
    if (approveToo) update.status = "approved";
    if (await run("save", () => onSave(memory, update))) setEditing(false);
  }

  return (
    <article
      className={cn(
        "rounded-2xl border bg-surface-raised p-4 sm:p-5",
        isCandidate ? "border-amber-400/30" : "border-border",
      )}
      aria-label={`${memoryTypeLabel(memory.memory_type)} memory`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-full border border-accent/40 px-2.5 py-0.5 font-medium text-accent-soft">
          {memoryTypeLabel(memory.memory_type)}
        </span>
        <span className={cn("rounded-full border px-2.5 py-0.5", STATUS_STYLES[memory.status])}>
          <span aria-hidden>{STATUS_ICONS[memory.status]} </span>
          {STATUS_LABELS[memory.status]}
        </span>
        <span className={cn("text-muted", memory.source === "conversation" && "text-amber-200/80")}>
          {sourceText(memory)}
        </span>
        {onVisibility && (
          <button
            type="button"
            onClick={() => run("visibility", () => onVisibility(memory, memory.visibility === "public" ? "private" : "public"))}
            disabled={busy !== null}
            aria-label={`Visibility: ${memory.visibility}. Click to make it ${memory.visibility === "public" ? "private" : "public"}.`}
            className={cn(
              "ml-auto inline-flex min-h-11 items-center rounded-full border px-3 py-0.5 md:min-h-0 md:px-2.5",
              memory.visibility === "public" ? "border-cyan/50 text-cyan" : "border-border text-muted hover:text-white",
            )}
          >
            {memory.visibility === "public" ? "🌐 Public" : "🔒 Private"}
          </button>
        )}
      </div>

      {editing ? (
        <div className="mt-3 space-y-3">
          <label className="sr-only" htmlFor={`type-${memory.id}`}>Memory type</label>
          <select
            id={`type-${memory.id}`}
            value={type}
            onChange={(e) => setType(e.target.value as MemoryType)}
            className={`${inputClass} max-sm:text-base`}
          >
            {MEMORY_TYPES.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <label className="sr-only" htmlFor={`content-${memory.id}`}>Memory</label>
          <textarea
            id={`content-${memory.id}`}
            rows={3}
            value={content}
            maxLength={MEMORY_MAX_CHARACTERS}
            onChange={(e) => setContent(e.target.value)}
            className={`${inputClass} max-sm:text-base`}
          />
        </div>
      ) : (
        <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-100">{memory.content}</p>
      )}

      {!compact && !editing && (
        <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <div className="flex gap-1.5">
            <dt>Confidence:</dt>
            <dd className="text-gray-200">{formatConfidence(memory.confidence)}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Created:</dt>
            <dd className="text-gray-200">{formatDate(memory.created_at)}</dd>
          </div>
          {memory.last_used_at && (
            <div className="flex gap-1.5">
              <dt>Last used:</dt>
              <dd className="text-gray-200">{formatDate(memory.last_used_at)}</dd>
            </div>
          )}
        </dl>
      )}

      {error && <p className="mt-3 text-sm text-rose-300" role="alert">{error}</p>}

      <div className="mt-4 flex flex-wrap gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={() => save(isCandidate)}
              disabled={busy !== null}
              className={cn(buttonClass, "border-accent bg-accent text-ink hover:bg-accent/90")}
            >
              {busy === "save" ? "Saving…" : isCandidate ? "Save & Approve" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={busy !== null}
              className={cn(buttonClass, "border-border text-muted hover:text-white")}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            {memory.status !== "approved" && (
              <button
                type="button"
                onClick={() => run("approve", () => onAction(memory, "approve"))}
                disabled={busy !== null}
                className={cn(buttonClass, "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10")}
              >
                {busy === "approve" ? "Approving…" : memory.status === "candidate" ? "Approve" : "Restore"}
              </button>
            )}
            <button
              type="button"
              onClick={startEditing}
              disabled={busy !== null}
              className={cn(buttonClass, "border-border text-muted hover:border-accent hover:text-white")}
            >
              {isCandidate ? "Edit & Approve" : "Edit"}
            </button>
            {isCandidate && (
              <button
                type="button"
                onClick={() => run("reject", () => onAction(memory, "reject"))}
                disabled={busy !== null}
                className={cn(buttonClass, "border-amber-400/40 text-amber-300 hover:bg-amber-400/10")}
              >
                {busy === "reject" ? "Rejecting…" : "Reject"}
              </button>
            )}
            {memory.status === "approved" && (
              <button
                type="button"
                onClick={() => run("archive", () => onAction(memory, "archive"))}
                disabled={busy !== null}
                className={cn(buttonClass, "border-border text-muted hover:text-white")}
              >
                {busy === "archive" ? "Archiving…" : "Archive"}
              </button>
            )}
            {!compact && (
              <button
                type="button"
                onClick={() => run("delete", () => onAction(memory, "delete"))}
                disabled={busy !== null}
                className={cn(buttonClass, "ml-auto border-rose-500/30 text-rose-300 hover:bg-rose-500/10")}
              >
                Delete
              </button>
            )}
          </>
        )}
      </div>
    </article>
  );
}
