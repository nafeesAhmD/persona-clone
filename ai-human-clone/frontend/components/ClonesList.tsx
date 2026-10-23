"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { useAuth } from "@/components/AuthProvider";
import { StatusBadge, VisibilityBadge } from "@/components/clone/CloneBadges";
import { CloneAvatar } from "@/components/CloneAvatar";
import { ChatIcon } from "@/components/mobile/icons";
import { getMyClones, listPublicClones } from "@/lib/api";
import { publicImageUrl } from "@/lib/publicApi";
import type { CloneSummary } from "@/types/clone";

const secondaryAction =
  "flex min-h-11 items-center justify-center rounded-xl border border-border px-3 text-sm text-gray-200 hover:border-accent hover:text-white";

/**
 * An owner's clone card: avatar, name, status and visibility (as text, not just
 * colour), a big Chat button and touch-friendly Edit / Analytics / Details / Share.
 */
export function MyCloneCard({ clone, onDelete }: { clone: CloneSummary; onDelete?: (clone: CloneSummary) => void }) {
  const canChat = clone.status !== "disabled";
  const headingId = `clone-${clone.id}-name`;

  return (
    <article aria-labelledby={headingId} className="flex h-full flex-col rounded-2xl border border-border bg-surface-raised p-4 sm:p-5">
      <div className="flex items-start gap-3 sm:gap-4">
        <CloneAvatar name={clone.name} src={publicImageUrl(clone.avatar_url)} />
        <div className="min-w-0 flex-1">
          <h3 id={headingId} className="truncate font-semibold">
            {clone.name}
          </h3>
          <p className="truncate text-sm text-muted">{clone.profession ?? "AI clone"}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusBadge status={clone.status} />
            <VisibilityBadge visibility={clone.visibility} />
          </div>
        </div>
      </div>

      {clone.skills.length > 0 && <p className="mt-3 line-clamp-2 text-sm text-gray-200">{clone.skills.join(" • ")}</p>}

      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <div className="flex gap-1.5">
          <dt className="text-muted">Knowledge:</dt>
          <dd>{clone.knowledge_count}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">Language:</dt>
          <dd>{clone.preferred_language ?? "—"}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">Public chat:</dt>
          <dd className={clone.public_chat_enabled ? "text-emerald-300" : "text-muted"}>
            {clone.public_chat_enabled ? "On" : "Off"}
          </dd>
        </div>
      </dl>

      <div className="mt-auto pt-4">
        {canChat ? (
          <Link
            href={`/clone/${clone.id}`}
            className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 font-medium text-ink shadow-lg shadow-accent/20 hover:bg-accent/90"
          >
            <ChatIcon className="h-5 w-5" />
            Chat<span className="sr-only"> with {clone.name}</span>
          </Link>
        ) : (
          <p className="flex min-h-12 w-full items-center justify-center rounded-xl border border-dashed border-border px-4 text-center text-sm text-muted">
            Chat is off while this clone is disabled
          </p>
        )}
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Link href={`/clone/${clone.id}/edit`} className={secondaryAction}>
            Edit<span className="sr-only"> {clone.name}</span>
          </Link>
          <Link href={`/clone/${clone.id}/analytics`} className={secondaryAction}>
            Analytics<span className="sr-only"> for {clone.name}</span>
          </Link>
          <Link href={`/clone/${clone.id}/details`} className={secondaryAction}>
            Details<span className="sr-only"> of {clone.name}</span>
          </Link>
          <Link
            href={`/clone/${clone.id}/sharing`}
            className="flex min-h-11 items-center justify-center rounded-xl border border-cyan/40 px-3 text-sm text-cyan hover:bg-cyan/10"
          >
            Share<span className="sr-only"> {clone.name}</span>
          </Link>
        </div>
        {onDelete && (
          <button
            type="button"
            onClick={() => onDelete(clone)}
            className="mt-2 flex min-h-11 w-full items-center justify-center rounded-xl border border-rose-500/30 px-3 text-sm text-rose-300 hover:bg-rose-500/10"
          >
            Delete<span className="sr-only"> {clone.name}</span>
          </button>
        )}
      </div>
    </article>
  );
}

/** A public clone visitors can talk to (no owner actions). */
function PublicCloneCard({ clone }: { clone: CloneSummary }) {
  return (
    <Link
      href={`/c/${clone.slug}`}
      className="flex min-h-20 items-center gap-4 rounded-2xl border border-border bg-surface-raised p-4 transition hover:border-accent sm:p-5"
    >
      <CloneAvatar name={clone.name} src={publicImageUrl(clone.avatar_url)} />
      <div className="min-w-0">
        <p className="truncate font-medium">{clone.name}</p>
        <p className="truncate text-sm text-muted">{clone.profession ?? "AI clone"}</p>
      </div>
    </Link>
  );
}

function MyClones() {
  const [clones, setClones] = useState<CloneSummary[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    getMyClones()
      .then((data) => {
        setClones(data);
        setError(null);
      })
      .catch(setError);
  }, []);

  useEffect(load, [load]);

  if (error) return <ApiErrorState error={error} thing="list" onRetry={load} />;
  if (!clones) return <p className="text-sm text-muted" role="status">Loading your clones…</p>;
  if (clones.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-8 text-center">
        <p className="font-medium">No AI Clones yet.</p>
        <Link
          href="/create-clone"
          className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-accent px-5 text-sm font-medium text-ink hover:bg-accent/90"
        >
          Create AI Clone
        </Link>
      </div>
    );
  }
  return (
    <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {clones.map((clone) => (
        <li key={clone.id}>
          <MyCloneCard clone={clone} />
        </li>
      ))}
    </ul>
  );
}

function PublicClones() {
  const [clones, setClones] = useState<CloneSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPublicClones()
      .then(setClones)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load clones"));
  }, []);

  if (error) return <p role="alert" className="text-sm text-rose-300">⚠ {error}</p>;
  if (!clones) return <p className="text-sm text-muted" role="status">Loading…</p>;

  if (clones.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-8 text-center">
        <p className="text-muted">No public clones yet.</p>
        <Link
          href="/create-clone"
          className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-accent px-5 text-sm font-medium text-ink hover:bg-accent/90"
        >
          Create the first one
        </Link>
      </div>
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
      {clones.map((clone) => (
        <li key={clone.id}>
          <PublicCloneCard clone={clone} />
        </li>
      ))}
    </ul>
  );
}

/** /clones: logged-in users see their own clones first, then public clones to talk to. */
export function ClonesList() {
  const { status } = useAuth();

  if (status === "loading") return <p className="text-sm text-muted" role="status">Loading…</p>;

  return (
    <div className="space-y-10">
      {status === "authenticated" && (
        <section aria-labelledby="my-clones-title">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 id="my-clones-title" className="text-lg font-semibold">
              My Clones
            </h2>
            <Link
              href="/create-clone"
              className="inline-flex min-h-11 items-center rounded-xl bg-accent px-4 text-sm font-medium text-ink hover:bg-accent/90"
            >
              Create AI Clone
            </Link>
          </div>
          <MyClones />
        </section>
      )}
      <section aria-labelledby="public-clones-title">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 id="public-clones-title" className="text-lg font-semibold">
            Public clones
          </h2>
          <Link href="/explore" className="inline-flex min-h-11 items-center text-sm text-accent-soft hover:underline">
            Explore all
          </Link>
        </div>
        <PublicClones />
      </section>
    </div>
  );
}
