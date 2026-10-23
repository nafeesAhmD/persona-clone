"use client";

import Link from "next/link";

import { type MemoryAction, MemoryCard } from "@/components/memory/MemoryCard";
import { approveMemory, rejectMemory, updateMemory } from "@/lib/api";
import type { CloneMemory, MemoryUpdatePayload } from "@/types/memory";

interface MemorySuggestionsProps {
  cloneId: string;
  suggestions: CloneMemory[];
  message: string;
  onChange: (suggestions: CloneMemory[]) => void;
  onClose: () => void;
}

/** Candidates found in the current conversation, reviewed right in the chat (owner only). */
export function MemorySuggestions({ cloneId, suggestions, message, onChange, onClose }: MemorySuggestionsProps) {
  const pending = suggestions.filter((m) => m.status === "candidate");
  const done = suggestions.length - pending.length;

  function replace(updated: CloneMemory) {
    onChange(suggestions.map((m) => (m.id === updated.id ? updated : m)));
  }

  async function handleAction(memory: CloneMemory, action: MemoryAction) {
    if (action === "approve") replace(await approveMemory(cloneId, memory.id));
    else if (action === "reject") replace(await rejectMemory(cloneId, memory.id));
  }

  async function handleSave(memory: CloneMemory, update: MemoryUpdatePayload) {
    replace(await updateMemory(cloneId, memory.id, update));
  }

  return (
    <section aria-label="Possible memories" className="rounded-2xl border border-amber-400/30 bg-amber-400/5 p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-amber-100">
            {suggestions.length > 0 ? "Possible memories found" : "No new memories"}
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            {suggestions.length > 0
              ? "AI suggested these from this conversation. Your clone only uses the ones you approve."
              : message}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="-mr-2 -mt-2 inline-flex min-h-11 min-w-11 items-center justify-center text-xs text-muted hover:text-white md:m-0 md:min-h-0 md:min-w-0"
          aria-label="Close suggestions"
        >
          Close
        </button>
      </div>
      {pending.length > 0 && (
        <div className="mt-3 space-y-2 pr-1 md:max-h-72 md:overflow-y-auto">
          {pending.map((memory) => (
            <MemoryCard key={memory.id} memory={memory} onAction={handleAction} onSave={handleSave} compact />
          ))}
        </div>
      )}
      {done > 0 && (
        <p className="mt-3 text-xs text-muted" aria-live="polite">
          {done} reviewed.{" "}
          <Link href={`/clone/${cloneId}/memory`} className="inline-block py-2 text-accent-soft hover:underline md:py-0">
            See all memories
          </Link>
        </p>
      )}
    </section>
  );
}
