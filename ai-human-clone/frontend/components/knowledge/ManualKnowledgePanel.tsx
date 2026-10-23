"use client";

import { type FormEvent, useState } from "react";

import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { addManualKnowledge } from "@/lib/api";
import { MANUAL_MAX_CHARACTERS, MANUAL_MIN_CHARACTERS, formatCount } from "@/lib/knowledge";
import type { DocumentListItem } from "@/types/clone";

interface ManualKnowledgePanelProps {
  cloneId: string;
  onAdded: (document: DocumentListItem) => void;
}

export function ManualKnowledgePanel({ cloneId, onAdded }: ManualKnowledgePanelProps) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [errors, setErrors] = useState<{ title?: string; content?: string }>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const length = content.trim().length;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = {
      title: title.trim() ? undefined : "Give this knowledge a title.",
      content:
        length < MANUAL_MIN_CHARACTERS
          ? `Write at least ${MANUAL_MIN_CHARACTERS} characters.`
          : length > MANUAL_MAX_CHARACTERS
            ? `Keep it under ${formatCount(MANUAL_MAX_CHARACTERS)} characters.`
            : undefined,
    };
    setErrors(nextErrors);
    if (nextErrors.title || nextErrors.content) return;

    setSaving(true);
    setApiError(null);
    try {
      const document = await addManualKnowledge(cloneId, { title: title.trim(), content: content.trim() });
      setTitle("");
      setContent("");
      onAdded(document);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Could not save the knowledge.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <Field label="Title" htmlFor="knowledge-title" error={errors.title}>
        <input
          id="knowledge-title"
          value={title}
          maxLength={255}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="My Programming Journey"
          className={`${inputClass} max-sm:text-base`}
        />
      </Field>
      <Field
        label="Knowledge"
        htmlFor="knowledge-content"
        hint={`${formatCount(length)} / ${formatCount(MANUAL_MAX_CHARACTERS)}`}
        error={errors.content}
      >
        <textarea
          id="knowledge-content"
          rows={8}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="I started learning Python and later moved to Django, FastAPI and AI development..."
          className={`${inputClass} max-sm:text-base`}
        />
      </Field>
      {apiError && <FormAlert>{apiError}</FormAlert>}
      <button type="submit" disabled={saving} className={primaryButtonClass}>
        {saving ? "Saving…" : "Add Knowledge"}
      </button>
    </form>
  );
}
