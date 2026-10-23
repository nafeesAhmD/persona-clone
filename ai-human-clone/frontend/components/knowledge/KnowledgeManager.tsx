"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FormAlert } from "@/components/FormField";
import { DocumentStatusBadge } from "@/components/knowledge/DocumentStatusBadge";
import { IndexingStatusBadge } from "@/components/knowledge/IndexingStatusBadge";
import { ManualKnowledgePanel } from "@/components/knowledge/ManualKnowledgePanel";
import { MemorySearchPanel } from "@/components/knowledge/MemorySearchPanel";
import { UploadPanel } from "@/components/knowledge/UploadPanel";
import { StatusMessage } from "@/components/StatusMessage";
import {
  deleteDocument,
  getClone,
  getCloneDocuments,
  indexDocument,
  reindexDocument,
  retryDocument,
  setDocumentVisibility,
} from "@/lib/api";
import { filterDocuments, formatCount, isDocumentBusy, sourceIcon, sourceLabel, stripPaths } from "@/lib/knowledge";
import { cn } from "@/lib/utils";
import type { CloneProfile, DocumentListItem } from "@/types/clone";

type Panel = "upload" | "manual";

interface Notice {
  kind: "success" | "error";
  text: string;
}

export function KnowledgeManager({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [documents, setDocuments] = useState<DocumentListItem[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [panel, setPanel] = useState<Panel>("upload");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [indexingId, setIndexingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DocumentListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    Promise.all([getClone(cloneId), getCloneDocuments(cloneId)])
      .then(([cloneData, docs]) => {
        setClone(cloneData);
        setDocuments(docs);
        setLoadError(null);
      })
      .catch(setLoadError);
  }, [cloneId]);

  useEffect(load, [load]);

  // While a document is still being read or indexed, check again every few seconds.
  const busy = Boolean(documents?.some(isDocumentBusy));
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      getCloneDocuments(cloneId).then(setDocuments).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [busy, cloneId]);

  function added(document: DocumentListItem) {
    setDocuments((prev) => [document, ...(prev ?? []).filter((d) => d.id !== document.id)]);
    setNotice(
      document.status === "failed"
        ? { kind: "error", text: `"${document.title}" was saved but its text couldn't be read: ${stripPaths(document.error_message)}` }
        : document.indexing_status === "indexing_failed"
          ? { kind: "error", text: `"${document.title}" was saved, but adding it to AI memory failed: ${stripPaths(document.indexing_error)}` }
          : {
              kind: "success",
              text: `"${document.title}" was added (${formatCount(document.character_count)} characters, ${document.chunk_count} memory chunks).`,
            },
    );
  }

  async function memory(document: DocumentListItem, action: "index" | "reindex") {
    setIndexingId(document.id);
    setNotice(null);
    try {
      const result = await (action === "index" ? indexDocument : reindexDocument)(cloneId, document.id);
      setDocuments(await getCloneDocuments(cloneId)); // fresh indexed_at / counts
      setNotice(
        result.status === "indexed"
          ? { kind: "success", text: `"${document.title}" is in AI memory (${result.chunk_count} chunks).` }
          : { kind: "error", text: `Indexing "${document.title}" failed: ${stripPaths(result.error) || "unknown error"}` },
      );
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Indexing failed." });
    } finally {
      setIndexingId(null);
    }
  }

  async function toggleVisibility(document: DocumentListItem) {
    const visibility = document.visibility === "public" ? "private" : "public";
    setNotice(null);
    try {
      const updated = await setDocumentVisibility(cloneId, document.id, visibility);
      setDocuments((prev) => (prev ?? []).map((d) => (d.id === updated.id ? updated : d)));
      setNotice({
        kind: "success",
        text: visibility === "public" ? `"${document.title}" is public: visitors' answers may use it.` : `"${document.title}" is private.`,
      });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not change visibility." });
    }
  }

  async function retry(document: DocumentListItem) {
    setRetryingId(document.id);
    setNotice(null);
    try {
      const updated = await retryDocument(cloneId, document.id);
      setDocuments((prev) => (prev ?? []).map((d) => (d.id === updated.id ? updated : d)));
      setNotice(
        updated.status === "ready"
          ? { kind: "success", text: `"${updated.title}" was processed successfully.` }
          : { kind: "error", text: `"${updated.title}" still failed: ${stripPaths(updated.error_message)}` },
      );
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Retry failed." });
    } finally {
      setRetryingId(null);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteDocument(cloneId, pendingDelete.id);
      setDocuments((prev) => (prev ?? []).filter((d) => d.id !== pendingDelete.id));
      setNotice({ kind: "success", text: `"${pendingDelete.title}" was removed.` });
      setPendingDelete(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Could not delete.");
    } finally {
      setDeleting(false);
    }
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={load} />;
  if (!clone || !documents) return <StatusMessage title="Loading knowledge…" />;

  return (
    <div className="mx-auto max-w-4xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <Link href={`/clone/${clone.id}/details`} className="inline-flex min-h-11 items-center text-sm text-muted hover:text-white md:min-h-0">
        ← Back to {clone.name}
      </Link>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">{clone.name}&apos;s Knowledge</h1>
      <p className="mt-2 text-muted">Add information your AI Clone can use later when answering questions.</p>

      <div className="mt-6 grid grid-cols-2 gap-2 sm:mt-8 sm:gap-3" role="tablist" aria-label="Add knowledge">
        {(
          [
            ["upload", "Upload Document", "PDF, DOCX or TXT"],
            ["manual", "Add Knowledge Manually", "Write or paste text"],
          ] as const
        ).map(([value, label, description]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={panel === value}
            onClick={() => setPanel(value)}
            className={cn(
              "min-h-11 rounded-2xl border px-3 py-3 text-left transition sm:px-5 sm:py-4",
              panel === value ? "border-accent bg-accent/10" : "border-border bg-surface-raised hover:border-accent/50",
            )}
          >
            <span className={cn("block text-sm font-medium sm:text-base", panel === value && "text-accent-soft")}>{label}</span>
            <span className="mt-0.5 block text-xs text-muted sm:text-sm">{description}</span>
          </button>
        ))}
      </div>

      <section className="mt-4 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" role="tabpanel">
        {panel === "upload" ? (
          <UploadPanel cloneId={clone.id} onUploaded={added} />
        ) : (
          <ManualKnowledgePanel cloneId={clone.id} onAdded={added} />
        )}
      </section>

      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      <section className="mt-10">
        <h2 className="text-lg font-semibold">Knowledge Sources ({documents.length})</h2>
        <p className="mt-1 text-sm text-muted">
          Everything is private by default. Public content can be used by visitors to your AI Clone.
        </p>
        {documents.length > 3 && (
          <div className="mt-4">
            <label htmlFor="knowledge-filter" className="sr-only">Search knowledge sources</label>
            <input
              id="knowledge-filter"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by title or file name…"
              className="min-h-11 w-full rounded-xl border border-border bg-surface px-4 py-2.5 text-sm outline-none placeholder:text-muted/70 focus:border-accent max-sm:text-base"
            />
          </div>
        )}
        {documents.length > 0 && filterDocuments(documents, query).length === 0 && (
          <p className="mt-3 rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
            No knowledge source matches &quot;{query.trim()}&quot;.
          </p>
        )}
        {documents.length === 0 ? (
          <p className="mt-3 rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted">
            No knowledge yet. Upload a document or add some text above.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {filterDocuments(documents, query).map((document) => (
              <li key={document.id} className="rounded-2xl border border-border bg-surface-raised p-4 sm:p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="text-2xl" aria-hidden>
                      {sourceIcon(document)}
                    </span>
                    <div className="min-w-0">
                      <Link href={`/clone/${clone.id}/knowledge/${document.id}`} className="-my-2 block truncate py-2 font-medium hover:underline">
                        {document.title}
                      </Link>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                        <span>{sourceLabel(document)}</span>
                        {document.status === "ready" && <span>{formatCount(document.character_count)} characters</span>}
                      </div>
                      <dl className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                        <div className="flex items-center gap-1.5">
                          <dt>Extraction:</dt>
                          <dd><DocumentStatusBadge status={document.status} /></dd>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <dt>AI Memory:</dt>
                          <dd><IndexingStatusBadge status={document.indexing_status} /></dd>
                        </div>
                        {document.indexing_status === "indexed" && (
                          <div className="flex items-center gap-1.5">
                            <dt>Chunks:</dt>
                            <dd className="text-gray-200">{document.chunk_count}</dd>
                          </div>
                        )}
                      </dl>
                      {document.error_message && (
                        <p className={cn("mt-2 text-xs", document.status === "failed" ? "text-rose-300" : "text-muted")}>
                          {stripPaths(document.error_message)}
                        </p>
                      )}
                      {document.indexing_status === "indexing_failed" && document.indexing_error && (
                        <p className="mt-1 text-xs text-rose-300">AI memory: {stripPaths(document.indexing_error)}</p>
                      )}
                    </div>
                  </div>
                  <div className="grid shrink-0 grid-cols-2 gap-2 text-sm min-[400px]:flex min-[400px]:flex-wrap [&>*]:inline-flex [&>*]:min-h-11 [&>*]:items-center [&>*]:justify-center md:[&>*]:min-h-0">
                    {document.status === "ready" && (
                      <button
                        type="button"
                        onClick={() => memory(document, document.indexing_status === "indexed" ? "reindex" : "index")}
                        disabled={indexingId === document.id || document.indexing_status === "indexing"}
                        className={cn(
                          "rounded-lg border px-3 py-1.5 disabled:opacity-50",
                          document.indexing_status === "indexing_failed"
                            ? "border-amber-400/40 text-amber-300 hover:bg-amber-400/10"
                            : "border-cyan/40 text-cyan hover:bg-cyan/10",
                        )}
                      >
                        {indexingId === document.id
                          ? "Indexing…"
                          : document.indexing_status === "indexed"
                            ? "Reindex"
                            : document.indexing_status === "indexing_failed"
                              ? "Retry"
                              : "Index Knowledge"}
                      </button>
                    )}
                    {document.status === "failed" && document.source_type === "file" && (
                      <button
                        type="button"
                        onClick={() => retry(document)}
                        disabled={retryingId === document.id}
                        className="rounded-lg border border-amber-400/40 px-3 py-1.5 text-amber-300 hover:bg-amber-400/10 disabled:opacity-50"
                      >
                        {retryingId === document.id ? "Retrying…" : "Retry"}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => toggleVisibility(document)}
                      aria-label={`Visibility: ${document.visibility}. Click to make it ${document.visibility === "public" ? "private" : "public"}.`}
                      className={cn(
                        "rounded-lg border px-3 py-1.5",
                        document.visibility === "public" ? "border-cyan/50 text-cyan" : "border-border text-muted hover:text-white",
                      )}
                    >
                      {document.visibility === "public" ? "🌐 Public" : "🔒 Private"}
                    </button>
                    <Link
                      href={`/clone/${clone.id}/knowledge/${document.id}`}
                      className="rounded-lg border border-border px-3 py-1.5 text-muted hover:border-accent hover:text-white"
                    >
                      View
                    </Link>
                    <button
                      type="button"
                      onClick={() => setPendingDelete(document)}
                      className="rounded-lg border border-rose-500/30 px-3 py-1.5 text-rose-300 hover:bg-rose-500/10"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <MemorySearchPanel cloneId={clone.id} />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete Knowledge?"
        message="This information will be removed from your AI Clone."
        confirmLabel="Delete"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={confirmDelete}
        onCancel={() => {
          setPendingDelete(null);
          setDeleteError(null);
        }}
      />
    </div>
  );
}
