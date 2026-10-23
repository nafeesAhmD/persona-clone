"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { DocumentStatusBadge } from "@/components/knowledge/DocumentStatusBadge";
import { IndexingStatusBadge } from "@/components/knowledge/IndexingStatusBadge";
import { StatusMessage } from "@/components/StatusMessage";
import { getDocument } from "@/lib/api";
import { displayFileName, formatBytes, formatCount, sourceIcon, sourceLabel, stripPaths } from "@/lib/knowledge";
import type { DocumentDetail } from "@/types/clone";

interface DocumentViewProps {
  cloneId: string;
  documentId: string;
}

export function DocumentView({ cloneId, documentId }: DocumentViewProps) {
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(() => {
    getDocument(cloneId, documentId)
      .then((data) => {
        setDocument(data);
        setError(null);
      })
      .catch(setError);
  }, [cloneId, documentId]);

  useEffect(load, [load]);

  if (error) return <ApiErrorState error={error} thing="document" onRetry={load} />;
  if (!document) return <StatusMessage title="Loading document…" />;

  const created = new Date(document.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

  return (
    <main className="mx-auto max-w-4xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <Link href={`/clone/${cloneId}/knowledge`} className="inline-flex min-h-11 items-center text-sm text-muted hover:text-white md:min-h-0">
        ← Back to knowledge
      </Link>

      <div className="mt-4 flex items-start gap-3">
        <span className="text-3xl" aria-hidden>
          {sourceIcon(document)}
        </span>
        <h1 className="min-w-0 break-words text-2xl font-bold tracking-tight sm:text-3xl">{document.title}</h1>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-4 rounded-2xl border border-border bg-surface-raised p-4 text-sm sm:grid-cols-3 sm:p-5">
        <Meta label="Source Type" value={document.source_type === "file" ? "Uploaded file" : "Manual knowledge"} />
        <Meta label="File Type" value={sourceLabel(document)} />
        <div>
          <dt className="text-xs uppercase tracking-wider text-muted">Extraction</dt>
          <dd className="mt-1">
            <DocumentStatusBadge status={document.status} />
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wider text-muted">AI Memory</dt>
          <dd className="mt-1">
            <IndexingStatusBadge status={document.indexing_status} />
          </dd>
        </div>
        <Meta label="Memory Chunks" value={String(document.chunk_count)} />
        <Meta label="Created" value={created} />
        <Meta label="Characters" value={formatCount(document.character_count)} />
        {document.source_type === "file" && <Meta label="File" value={`${displayFileName(document.original_filename) || "—"} (${formatBytes(document.file_size)})`} />}
      </dl>

      {document.error_message && (
        <p className={`mt-4 text-sm ${document.status === "failed" ? "text-rose-300" : "text-muted"}`}>{stripPaths(document.error_message)}</p>
      )}

      <section className="mt-6">
        <h2 className="font-semibold">Extracted Text</h2>
        {document.extracted_text ? (
          // Plain text only: React escapes it, and nothing here is parsed as HTML or Markdown.
          <pre className="mt-3 max-h-[70dvh] overflow-auto whitespace-pre-wrap break-words rounded-2xl border border-border bg-surface p-4 sm:p-5 font-sans text-sm leading-relaxed text-gray-200">
            {document.extracted_text}
          </pre>
        ) : (
          <p className="mt-3 rounded-2xl border border-dashed border-border p-8 text-center text-sm text-muted">
            No text available for this document.
          </p>
        )}
      </section>
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-1 break-words">{value}</dd>
    </div>
  );
}
