"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { useAuth } from "@/components/AuthProvider";
import { MyCloneCard } from "@/components/ClonesList";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { deleteClone, getMyClones } from "@/lib/api";
import type { CloneSummary } from "@/types/clone";

export function Dashboard() {
  const { user } = useAuth();
  const [clones, setClones] = useState<CloneSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pendingDelete, setPendingDelete] = useState<CloneSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(() => {
    getMyClones()
      .then((data) => {
        setClones(data);
        setError(null);
      })
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteClone(pendingDelete.id);
      setPendingDelete(null);
      load(); // refresh from the server
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Could not delete the clone.");
    } finally {
      setDeleting(false);
    }
  }

  const name = user?.full_name || user?.username;

  return (
    <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-16">
      <section className="flex flex-col gap-5 rounded-2xl border border-border bg-surface-raised p-5 sm:flex-row sm:items-center sm:justify-between sm:p-8">
        <div>
          <p className="text-xs uppercase tracking-wider text-muted">Clone Me</p>
          <h1 className="mt-1 break-words text-2xl font-bold tracking-tight sm:text-3xl">Welcome, {name}</h1>
        </div>
        <Link
          href="/create-clone"
          className="flex min-h-12 items-center justify-center rounded-xl bg-accent px-5 text-center font-medium text-ink shadow-lg shadow-accent/25 transition hover:bg-accent/90"
        >
          Create AI Clone
        </Link>
      </section>

      <section className="mt-8 sm:mt-10" aria-labelledby="dashboard-clones-title">
        <h2 id="dashboard-clones-title" className="text-lg font-semibold">My Clones</h2>

        {error ? (
          <ApiErrorState error={error} thing="list" onRetry={load} />
        ) : clones === null ? (
          <p className="mt-3 text-sm text-muted" role="status">Loading…</p>
        ) : clones.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-border p-10 text-center">
            <p className="font-medium">No AI Clones yet.</p>
            <p className="mt-1 text-sm text-muted">Create your first digital AI Clone.</p>
            <Link
              href="/create-clone"
              className="mt-5 inline-flex min-h-11 items-center rounded-xl bg-accent px-5 text-sm font-medium text-ink hover:bg-accent/90"
            >
              Create AI Clone
            </Link>
          </div>
        ) : (
          <ul className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            {clones.map((clone) => (
              <li key={clone.id}>
                <MyCloneCard clone={clone} onDelete={setPendingDelete} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete "${pendingDelete?.name ?? ""}"?`}
        message="This action will remove this AI Clone, its uploaded knowledge and its conversations. It can't be undone."
        confirmLabel="Delete Clone"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteError(null);
        }}
      />
    </main>
  );
}
