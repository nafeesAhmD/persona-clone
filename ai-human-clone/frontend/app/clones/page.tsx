import type { Metadata } from "next";

import { ClonesList } from "@/components/ClonesList";

export const metadata: Metadata = {
  title: "Clones · Clone Me",
};

export default function ClonesPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-16">
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Clones</h1>
      <p className="mt-2 text-muted">
        Each clone is an AI built by its owner from their own information. You&apos;re always chatting with an AI.
      </p>
      <div className="mt-8">
        <ClonesList />
      </div>
    </main>
  );
}
