"use client";

import { type FormEvent, useState } from "react";

import { Field, FormAlert, inputClass } from "@/components/FormField";
import { createMemory } from "@/lib/api";
import { MEMORY_MAX_CHARACTERS, MEMORY_TYPES } from "@/lib/memory";
import type { CloneMemory, MemoryType } from "@/types/memory";

interface AddMemoryFormProps {
  cloneId: string;
  onAdded: (memory: CloneMemory) => void;
}

export function AddMemoryForm({ cloneId, onAdded }: AddMemoryFormProps) {
  const [type, setType] = useState<MemoryType>("communication_preference");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = content.trim();
    if (!text) {
      setError("Write what your clone should remember.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const memory = await createMemory(cloneId, { memory_type: type, content: text });
      setContent("");
      onAdded(memory);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the memory.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      <Field label="Memory Type" htmlFor="memory-type">
        <select
          id="memory-type"
          value={type}
          onChange={(e) => setType(e.target.value as MemoryType)}
          className={`${inputClass} max-sm:text-base`}
        >
          {MEMORY_TYPES.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </Field>
      <Field label="Content" htmlFor="memory-content" hint={`${content.trim().length} / ${MEMORY_MAX_CHARACTERS}`}>
        <textarea
          id="memory-content"
          rows={3}
          value={content}
          maxLength={MEMORY_MAX_CHARACTERS}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Always explain technical concepts in simple language."
          className={`${inputClass} max-sm:text-base`}
        />
      </Field>
      <p className="text-xs text-muted">
        Never add passwords, keys or other secrets: they are refused.
      </p>
      {error && <FormAlert>{error}</FormAlert>}
      <button
        type="submit"
        disabled={saving}
        className="min-h-11 w-full rounded-xl bg-accent px-5 py-2.5 text-sm font-medium sm:w-auto text-ink hover:bg-accent/90 disabled:cursor-wait disabled:opacity-60"
      >
        {saving ? "Saving…" : "Save Memory"}
      </button>
    </form>
  );
}
