"use client";

import Link from "next/link";
import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FormAlert } from "@/components/FormField";
import { AddMemoryForm } from "@/components/memory/AddMemoryForm";
import { type MemoryAction, MemoryCard } from "@/components/memory/MemoryCard";
import { StatusMessage } from "@/components/StatusMessage";
import {
  approveMemory,
  clearMemories,
  deleteMemory,
  getClone,
  getMemories,
  rejectMemory,
  setMemoryVisibility,
  updateMemory,
} from "@/lib/api";
import { MEMORY_TABS, nextTab } from "@/lib/memory";
import { cn } from "@/lib/utils";
import type { CloneProfile } from "@/types/clone";
import type { CloneMemory, MemoryStatus, MemoryUpdatePayload } from "@/types/memory";

interface Notice {
  kind: "success" | "error";
  text: string;
}

export function MemoryManager({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [memories, setMemories] = useState<CloneMemory[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [tab, setTab] = useState<MemoryStatus>("approved");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CloneMemory | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const tabRefs = useRef<Partial<Record<MemoryStatus, HTMLButtonElement | null>>>({});

  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const next = nextTab(tab, event.key);
    if (!next) return;
    event.preventDefault();
    setTab(next);
    tabRefs.current[next]?.focus();
  }

  const load = useCallback(() => {
    Promise.all([getClone(cloneId), getMemories(cloneId)])
      .then(([cloneData, list]) => {
        setClone(cloneData);
        setMemories(list);
        setLoadError(null);
        // Open on the suggestions when some are waiting for review.
        if (list.some((m) => m.status === "candidate") && !list.some((m) => m.status === "approved")) {
          setTab("candidate");
        }
      })
      .catch(setLoadError);
  }, [cloneId]);

  useEffect(load, [load]);

  function replace(updated: CloneMemory) {
    setMemories((prev) => (prev ?? []).map((m) => (m.id === updated.id ? updated : m)));
  }

  async function handleAction(memory: CloneMemory, action: MemoryAction) {
    setNotice(null);
    if (action === "delete") {
      setDialogError(null);
      setPendingDelete(memory);
      return;
    }
    const updated =
      action === "approve"
        ? await approveMemory(cloneId, memory.id)
        : action === "reject"
          ? await rejectMemory(cloneId, memory.id)
          : await updateMemory(cloneId, memory.id, { status: "archived" });
    replace(updated);
    setNotice({
      kind: "success",
      text:
        action === "approve"
          ? "Memory approved. Your clone will use it in future conversations."
          : action === "reject"
            ? "Suggestion rejected. It won't be used or suggested again."
            : "Memory archived. Your clone no longer uses it.",
    });
  }

  async function handleSave(memory: CloneMemory, update: MemoryUpdatePayload) {
    setNotice(null);
    replace(await updateMemory(cloneId, memory.id, update));
    setNotice({ kind: "success", text: update.status === "approved" ? "Memory edited and approved." : "Memory updated." });
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    setDialogError(null);
    try {
      await deleteMemory(cloneId, pendingDelete.id);
      setMemories((prev) => (prev ?? []).filter((m) => m.id !== pendingDelete.id));
      setNotice({ kind: "success", text: "Memory deleted." });
      setPendingDelete(null);
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : "Could not delete the memory.");
    } finally {
      setBusy(false);
    }
  }

  async function confirmClearAll() {
    setBusy(true);
    setDialogError(null);
    try {
      const { deleted } = await clearMemories(cloneId);
      setMemories([]);
      setNotice({ kind: "success", text: `All memories deleted (${deleted}). Your documents were not touched.` });
      setConfirmClear(false);
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : "Could not delete the memories.");
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={load} />;
  if (!clone || !memories) return <StatusMessage title="Loading memory…" />;

  const counts = Object.fromEntries(
    MEMORY_TABS.map(({ status }) => [status, memories.filter((m) => m.status === status).length]),
  ) as Record<MemoryStatus, number>;
  const current = MEMORY_TABS.find((t) => t.status === tab)!;
  const visible = memories.filter((m) => m.status === tab);

  return (
    <div className="mx-auto max-w-4xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Link href={`/clone/${clone.id}/details`} className="inline-flex min-h-11 items-center text-muted hover:text-white md:min-h-0">
          ← Back to {clone.name}
        </Link>
        <Link href={`/clone/${clone.id}`} className="inline-flex min-h-11 items-center text-accent-soft hover:underline md:min-h-0">
          Open chat
        </Link>
      </div>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Long-Term Memory</h1>
      <p className="mt-2 text-muted">These are the things your AI Clone is allowed to remember.</p>
      <p className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-200">
        Your AI Clone only uses memories that you approve. Memories are private by default; public content can be used
        by visitors to your AI Clone.
      </p>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-4 sm:mt-8 sm:p-7">
        <h2 className="text-lg font-semibold">Add Memory</h2>
        <p className="mt-1 text-sm text-muted">Memories you add yourself are approved right away.</p>
        <div className="mt-5">
          <AddMemoryForm
            cloneId={clone.id}
            onAdded={(memory) => {
              setMemories((prev) => [memory, ...(prev ?? [])]);
              setTab("approved");
              setNotice({ kind: "success", text: "Memory saved and approved." });
            }}
          />
        </div>
      </section>

      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      <section className="mt-10">
        {/* Segmented control: four equal columns that still fit a 320px screen. */}
        <div
          className="grid grid-cols-4 gap-1 rounded-2xl border border-border bg-surface-raised p-1 sm:inline-grid sm:auto-cols-fr sm:grid-flow-col"
          role="tablist"
          aria-label="Memories by status"
        >
          {MEMORY_TABS.map(({ status, label, icon }) => (
            <button
              key={status}
              ref={(element) => {
                tabRefs.current[status] = element;
              }}
              id={`memory-tab-${status}`}
              type="button"
              role="tab"
              aria-selected={tab === status}
              aria-controls="memory-tabpanel"
              tabIndex={tab === status ? 0 : -1}
              onClick={() => setTab(status)}
              onKeyDown={onTabKey}
              className={cn(
                "flex min-h-12 min-w-0 flex-col items-center justify-center rounded-xl px-1 py-1 text-[12px] leading-tight transition sm:flex-row sm:gap-1.5 sm:px-4 sm:text-sm",
                tab === status ? "bg-accent/20 font-medium text-accent-soft" : "text-muted hover:text-white",
              )}
            >
              <span className="flex items-center gap-1">
                <span aria-hidden className="hidden min-[360px]:inline">{icon}</span>
                {label}
              </span>
              <span className="tabular-nums text-[11px] opacity-80 sm:text-sm">({counts[status]})</span>
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-3" role="tabpanel" id="memory-tabpanel" aria-labelledby={`memory-tab-${tab}`}>
          {tab === "candidate" && visible.length > 0 && (
            <p className="text-sm text-amber-200/90">
              The AI suggested these from your conversations. Nothing here is used until you approve it.
            </p>
          )}
          {visible.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted">{current.empty}</p>
          ) : (
            visible.map((memory) => (
              <MemoryCard
                key={memory.id}
                memory={memory}
                onAction={handleAction}
                onSave={handleSave}
                onVisibility={async (item, visibility) => {
                  replace(await setMemoryVisibility(cloneId, item.id, visibility));
                  setNotice({
                    kind: "success",
                    text: visibility === "public" ? "Memory is now public: visitors' answers may use it once approved." : "Memory is now private.",
                  });
                }}
              />
            ))
          )}
        </div>
      </section>

      <section className="mt-12 rounded-2xl border border-rose-500/20 p-5">
        <h2 className="font-semibold">Delete all memories</h2>
        <p className="mt-1 text-sm text-muted">
          Removes every memory of this clone, including suggestions. Uploaded documents and conversations stay.
        </p>
        <button
          type="button"
          onClick={() => {
            setDialogError(null);
            setConfirmClear(true);
          }}
          disabled={memories.length === 0}
          className="mt-4 min-h-11 rounded-xl border border-rose-500/40 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
        >
          Delete all memories
        </button>
      </section>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this memory?"
        message="Your AI Clone will forget it permanently."
        confirmLabel="Delete"
        busyLabel="Deleting…"
        busy={busy}
        error={dialogError}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
      <ConfirmDialog
        open={confirmClear}
        title="Delete all memories?"
        message={`All ${memories.length} memories of ${clone.name} will be deleted permanently. Documents and conversations are not affected.`}
        confirmLabel="Delete all memories"
        busyLabel="Deleting…"
        busy={busy}
        error={dialogError}
        onConfirm={confirmClearAll}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  );
}
