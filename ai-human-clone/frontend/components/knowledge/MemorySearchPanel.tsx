"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { FormAlert, inputClass } from "@/components/FormField";
import { searchKnowledge } from "@/lib/api";
import { sourceIcon } from "@/lib/knowledge";
import type { KnowledgeSearchResponse } from "@/types/clone";

/**
 * Developer tool: runs a semantic search over the clone's memory and shows the
 * raw matching chunks with their similarity scores. No AI answer is generated.
 */
export function MemorySearchPanel({ cloneId }: { cloneId: string }) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [searching, setSearching] = useState(false);
  const [response, setResponse] = useState<KnowledgeSearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Opened via "Test AI Memory" (…/knowledge#memory-test): the section renders after
  // data loads, so the browser can't jump to it by itself.
  useEffect(() => {
    if (window.location.hash === "#memory-test") {
      sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      inputRef.current?.focus({ preventScroll: true });
    }
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      setResponse(await searchKnowledge(cloneId, query.trim(), topK));
    } catch (err) {
      setResponse(null);
      setError(err instanceof Error ? err.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  }

  return (
    <section ref={sectionRef} id="memory-test" className="mt-10 scroll-mt-24 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7">
      <h2 className="text-lg font-semibold">Test AI Memory</h2>
      <p className="mt-1 text-sm text-muted">
        Search what your clone can recall. This shows the raw knowledge chunks it would use, ranked by similarity. It
        does not generate an answer.
      </p>

      <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="memory-query" className="sr-only">
          Search query
        </label>
        <input
          id="memory-query"
          ref={inputRef}
          value={query}
          maxLength={1000}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask something about this clone's knowledge..."
          className={`${inputClass} max-sm:text-base`}
        />
        <label htmlFor="memory-top-k" className="sr-only">
          Number of results
        </label>
        <select
          id="memory-top-k"
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
          className="rounded-xl border border-border bg-surface px-3 py-3 text-sm sm:w-28"
        >
          {[3, 5, 10, 20].map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={searching || !query.trim()}
          className="shrink-0 rounded-xl bg-accent px-5 py-3 text-sm font-medium text-ink hover:bg-accent/90 disabled:opacity-50"
        >
          {searching ? "Searching…" : "Search Memory"}
        </button>
      </form>

      {error && (
        <div className="mt-4">
          <FormAlert>{error}</FormAlert>
        </div>
      )}

      {response && (
        <div className="mt-6" aria-live="polite">
          <h3 className="text-sm font-semibold">Relevant Sources</h3>
          {response.results.length === 0 ? (
            <p className="mt-2 rounded-xl border border-dashed border-border p-5 text-center text-sm text-muted">
              {response.message ?? "No results."}
            </p>
          ) : (
            <ol className="mt-3 space-y-3">
              {response.results.map((result) => (
                <li key={`${result.document_id}-${result.chunk_index}`} className="rounded-xl border border-border bg-surface p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className="min-w-0 truncate font-medium text-gray-100">
                      <span aria-hidden>{sourceIcon(result)} </span>
                      {result.title} <span className="text-muted">· chunk {result.chunk_index + 1}</span>
                    </span>
                    <span className="rounded-full border border-cyan/40 px-2 py-0.5 font-mono text-cyan" title="Cosine similarity">
                      score {result.score.toFixed(3)}
                    </span>
                  </div>
                  {/* Untrusted document text: rendered as plain text only. */}
                  <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-200">{result.text}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
