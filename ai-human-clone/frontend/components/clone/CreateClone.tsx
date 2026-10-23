"use client";

import { useRouter } from "next/navigation";

import { CloneForm } from "@/components/clone/CloneForm";
import { createClone } from "@/lib/api";

export function CreateClone() {
  const router = useRouter();

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-16">
      <h1 className="break-words text-2xl font-bold tracking-tight sm:text-3xl">Create your AI clone</h1>
      <p className="mt-2 text-muted">
        Describe yourself and how your clone should talk. You can change everything later.
      </p>
      <div className="mt-6 sm:mt-8">
        <CloneForm
          mode="create"
          cancelHref="/dashboard"
          onSubmit={async (settings, ownerConsent) => {
            const clone = await createClone({ ...settings, owner_consent: ownerConsent });
            router.push(`/clone/${clone.id}/details`);
          }}
        />
      </div>
    </main>
  );
}
