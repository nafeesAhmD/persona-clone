"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { CloneForm } from "@/components/clone/CloneForm";
import { StatusMessage } from "@/components/StatusMessage";
import { getClone, updateClone } from "@/lib/api";
import type { CloneProfile } from "@/types/clone";

export function EditClone({ cloneId }: { cloneId: string }) {
  const router = useRouter();
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    getClone(cloneId)
      .then((data) => {
        setClone(data);
        setError(null);
      })
      .catch(setError);
  }, [cloneId]);

  useEffect(load, [load]);

  if (error) return <ApiErrorState error={error} thing="clone" onRetry={load} />;
  if (!clone) return <StatusMessage title="Loading clone…" />;

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-16">
      <h1 className="break-words text-2xl font-bold tracking-tight sm:text-3xl">Edit {clone.name}</h1>
      <p className="mt-2 text-muted">Changes apply to new conversations right away.</p>
      <div className="mt-6 sm:mt-8">
        <CloneForm
          mode="edit"
          initial={clone}
          cancelHref={`/clone/${clone.id}/details`}
          onSubmit={async (settings) => {
            await updateClone(clone.id, settings);
            router.push(`/clone/${clone.id}/details?saved=1`);
          }}
        />
      </div>
    </main>
  );
}
