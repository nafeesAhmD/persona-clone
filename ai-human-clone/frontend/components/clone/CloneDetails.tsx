"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { StatusBadge, VisibilityBadge } from "@/components/clone/CloneBadges";
import { CloneAvatar } from "@/components/CloneAvatar";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FormAlert } from "@/components/FormField";
import { StatusMessage } from "@/components/StatusMessage";
import { RealismChecklist } from "@/components/voice/RealismChecklist";
import { deleteClone, getClone } from "@/lib/api";
import { RESPONSE_LENGTHS, VISIBILITIES, labelFor } from "@/lib/clone-options";
import { publicImageUrl } from "@/lib/publicApi";
import type { CloneProfile } from "@/types/clone";

const actionClass =
  "flex min-h-11 items-center justify-center rounded-xl border border-border px-5 text-center text-sm hover:border-accent";

interface CloneDetailsProps {
  cloneId: string;
  justSaved?: boolean;
}

export function CloneDetails({ cloneId, justSaved = false }: CloneDetailsProps) {
  const router = useRouter();
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const load = useCallback(() => {
    getClone(cloneId)
      .then((data) => {
        setClone(data);
        setError(null);
      })
      .catch(setError);
  }, [cloneId]);

  useEffect(load, [load]);

  async function handleDelete() {
    if (!clone) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteClone(clone.id);
      router.push("/dashboard");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Could not delete the clone.");
      setDeleting(false);
    }
  }

  if (error) return <ApiErrorState error={error} thing="clone" onRetry={load} />;
  if (!clone) return <StatusMessage title="Loading clone…" />;

  const canChat = clone.status !== "disabled";

  return (
    <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-16">
      {justSaved && (
        <div className="mb-6">
          <FormAlert kind="success">Changes saved.</FormAlert>
        </div>
      )}

      <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
          <CloneAvatar name={clone.name} size="xl" src={publicImageUrl(clone.avatar_url)} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="break-words text-2xl font-bold tracking-tight sm:text-3xl">{clone.name}</h1>
              <StatusBadge status={clone.status} />
              <VisibilityBadge visibility={clone.visibility} />
            </div>
            {clone.tagline && <p className="mt-1 text-muted">{clone.tagline}</p>}
            {clone.profession && <p className="mt-2 text-sm">{clone.profession}</p>}
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-2 sm:flex sm:flex-row sm:gap-3">
          {canChat ? (
            <Link
              href={`/clone/${clone.id}`}
              className="col-span-2 flex min-h-12 items-center justify-center rounded-xl bg-accent px-5 text-center font-medium text-ink hover:bg-accent/90 sm:min-h-11 sm:text-sm"
            >
              Chat
            </Link>
          ) : (
            <span
              aria-disabled="true"
              className="col-span-2 flex min-h-12 cursor-not-allowed items-center justify-center rounded-xl bg-accent/40 px-5 text-center text-sm font-medium text-white/70 sm:min-h-11"
            >
              Chat (disabled)
            </span>
          )}
          <Link href={`/clone/${clone.id}/edit`} className={actionClass}>
            Edit Clone
          </Link>
          <Link href={`/clone/${clone.id}/analytics`} className={actionClass}>
            Analytics
          </Link>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="col-span-2 flex min-h-11 items-center justify-center rounded-xl border border-rose-500/40 px-5 text-sm text-rose-300 hover:bg-rose-500/10 sm:ml-auto"
          >
            Delete
          </button>
        </div>
        {clone.status === "disabled" && (
          <p className="mt-3 text-xs text-rose-300">Chat is turned off while this clone is disabled.</p>
        )}
      </section>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-6 lg:col-span-2">
          <h2 className="font-semibold">About</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-gray-200">{clone.bio || <span className="text-muted">No bio yet.</span>}</p>

          <h2 className="mt-6 font-semibold">Skills</h2>
          {clone.skills.length > 0 ? (
            <ul className="mt-3 flex flex-wrap gap-2">
              {clone.skills.map((skill) => (
                <li key={skill} className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-sm text-accent-soft">
                  {skill}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">No skills added.</p>
          )}

          <h2 className="mt-6 font-semibold">Personality</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm text-gray-200">
            {clone.personality_description || <span className="text-muted">Not described.</span>}
          </p>
        </section>

        <aside className="space-y-6">
          <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-6">
            <h2 className="font-semibold">Settings</h2>
            <dl className="mt-4 space-y-3 text-sm">
              <Setting label="Language" value={clone.preferred_language || "Same as visitor"} />
              <Setting label="Communication Style" value={clone.communication_style || "—"} />
              <Setting label="Response Length" value={labelFor(RESPONSE_LENGTHS, clone.response_length)} />
              <Setting label="Visibility" value={labelFor(VISIBILITIES, clone.visibility)} />
              <Setting label="Status" value={clone.status[0].toUpperCase() + clone.status.slice(1)} />
              <Setting label="Link name" value={clone.slug} />
            </dl>
          </section>

          <section className="rounded-2xl border border-border bg-surface-raised p-5 sm:p-6">
            <h2 className="font-semibold">Knowledge</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <Setting label="Knowledge Sources" value={String(clone.knowledge_count)} />
              <Setting label="Indexed Sources" value={String(clone.indexed_count)} />
              <Setting label="Memory Chunks" value={String(clone.chunk_count)} />
            </dl>
            <p className="mt-3 text-sm text-muted">
              {clone.knowledge_count === 0
                ? "Your AI Clone needs knowledge to answer personal questions."
                : clone.indexed_count < clone.knowledge_count
                  ? "Some knowledge isn't in AI memory yet. Index it from the knowledge page."
                  : "All knowledge is in AI memory and can be searched."}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                href={`/clone/${clone.id}/knowledge`}
                className="inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
              >
                Manage Knowledge
              </Link>
              <Link
                href={`/clone/${clone.id}/knowledge#memory-test`}
                className="inline-flex min-h-11 items-center rounded-xl border border-cyan/40 px-4 py-2 text-sm text-cyan hover:bg-cyan/10"
              >
                Test AI Memory
              </Link>
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-surface-raised p-5">
            <h2 className="font-semibold">Long-Term Memory</h2>
            <p className="mt-2 text-sm text-muted">
              Facts and preferences your clone remembers about you. It only uses the ones you approve.
            </p>
            <Link
              href={`/clone/${clone.id}/memory`}
              className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
            >
              Manage Memory
            </Link>
          </section>

          <section className="rounded-2xl border border-border bg-surface-raised p-5">
            <h2 className="font-semibold">AI Agent</h2>
            <p className="mt-2 text-sm text-muted">
              Let your clone work on tasks in visible steps, using only the tools you allow. Off until you turn it on.
            </p>
            <Link
              href={`/clone/${clone.id}/agent`}
              className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-cyan/40 px-4 py-2 text-sm text-cyan hover:bg-cyan/10"
            >
              AI Agent
            </Link>
          </section>

          <RealismChecklist cloneId={clone.id} />

          <section className="rounded-2xl border border-border bg-surface-raised p-5">
            <h2 className="font-semibold">Voice</h2>
            <p className="mt-2 text-sm text-muted">
              Talk to your clone and hear it answer with an AI-generated voice, or clone your own voice. Needs your voice consent.
            </p>
            <Link
              href={`/clone/${clone.id}/voice`}
              className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
            >
              Voice Settings
            </Link>
          </section>

          <section className="rounded-2xl border border-border bg-surface-raised p-5">
            <h2 className="font-semibold">Avatar</h2>
            <p className="mt-2 text-sm text-muted">
              A talking avatar that speaks your clone&apos;s answers. Clearly labelled as AI-generated. Needs your consent.
            </p>
            <Link
              href={`/clone/${clone.id}/avatar`}
              className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
            >
              Avatar Settings
            </Link>
          </section>

          <section className="rounded-2xl border border-border bg-surface-raised p-5">
            <h2 className="font-semibold">Share</h2>
            <p className="mt-2 text-sm text-muted">
              Give people a link to chat with your clone. Only content you mark public is used.
            </p>
            <Link
              href={`/clone/${clone.id}/sharing`}
              className="mt-4 inline-flex min-h-11 items-center rounded-xl border border-cyan/40 px-4 py-2 text-sm text-cyan hover:bg-cyan/10"
            >
              Share Clone
            </Link>
          </section>
        </aside>
      </div>

      <ConfirmDialog
        open={confirming}
        title={`Delete "${clone.name}"?`}
        message="This action will remove this AI Clone, its uploaded knowledge and its conversations. It can't be undone."
        confirmLabel="Delete Clone"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={handleDelete}
        onCancel={() => {
          setConfirming(false);
          setDeleteError(null);
        }}
      />
    </main>
  );
}

function Setting({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-right">{value}</dd>
    </div>
  );
}
