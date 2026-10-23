"use client";

import { type DragEvent, useRef, useState } from "react";

import { Field, FormAlert, inputClass, primaryButtonClass } from "@/components/FormField";
import { uploadDocument } from "@/lib/api";
import { ACCEPT_ATTRIBUTE, MAX_UPLOAD_MB, displayFileName, formatBytes, validateUploadFile } from "@/lib/knowledge";
import { cn } from "@/lib/utils";
import type { DocumentListItem } from "@/types/clone";

interface UploadPanelProps {
  cloneId: string;
  onUploaded: (document: DocumentListItem) => void;
  /** The server's upload limit in MB when known (defaults to MAX_UPLOAD_MB). */
  maxUploadMb?: number;
}

export function UploadPanel({ cloneId, onUploaded, maxUploadMb = MAX_UPLOAD_MB }: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const uploading = progress !== null;

  function choose(selected: File | undefined) {
    if (!selected) return;
    setError(validateUploadFile(selected, maxUploadMb));
    setFailed(false);
    setFile(selected);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (!uploading) choose(event.dataTransfer.files[0]);
  }

  async function handleUpload() {
    if (!file) return;
    const problem = validateUploadFile(file, maxUploadMb);
    if (problem) return setError(problem);

    setError(null);
    setFailed(false);
    setProgress(0);
    try {
      const document = await uploadDocument(cloneId, file, { title, onProgress: setProgress });
      setFile(null);
      setTitle("");
      onUploaded(document);
    } catch (err) {
      setFailed(true); // the file stays selected: "Retry upload" sends it again on tap
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setProgress(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const percent = progress === null ? 0 : Math.round(progress * 100);

  return (
    <div className="space-y-5">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={cn(
          "rounded-2xl border-2 border-dashed px-4 py-6 text-center transition sm:px-6 sm:py-10",
          dragging ? "border-accent bg-accent/10" : "border-border bg-surface",
        )}
      >
        <p className="text-3xl" aria-hidden>
          📄
        </p>
        <p className="mt-3 hidden font-medium pointer-fine:block">Drag &amp; drop your document here</p>
        <p className="mt-1 hidden text-sm text-muted pointer-fine:block">or</p>
        <button
          type="button"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
          className="mt-3 min-h-11 rounded-xl border border-border px-5 py-2 text-sm font-medium hover:border-accent disabled:opacity-50"
        >
          {file ? "Choose another file" : "Choose File"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          className="hidden"
          aria-label="Knowledge file"
          onChange={(e) => choose(e.target.files?.[0])}
        />
        <p className="mt-4 text-xs text-muted">
          Supported: PDF • DOCX • TXT &nbsp;·&nbsp; Maximum: {maxUploadMb} MB
        </p>
      </div>

      {file && (
        <div className="rounded-xl border border-border bg-surface px-4 py-3 text-sm">
          <div className="flex items-center justify-between gap-4">
            <span className="min-w-0 truncate font-medium">{displayFileName(file.name)}</span>
            <span className="shrink-0 text-muted">{formatBytes(file.size)}</span>
          </div>
          {uploading && (
            <div className="mt-3">
              <div
                className="h-2 overflow-hidden rounded-full bg-border"
                role="progressbar"
                aria-label="Upload progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
              >
                <div
                  className={cn("h-full bg-accent transition-all", progress >= 1 && "animate-pulse motion-reduce:animate-none")}
                  style={{ width: `${percent}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-muted" aria-live="polite">
                {progress < 1 ? `Uploading… ${percent}%` : "Processing document…"}
              </p>
            </div>
          )}
        </div>
      )}

      {file && (
        <Field label="Title" htmlFor="upload-title" hint="Optional: defaults to the file name">
          <input
            id="upload-title"
            value={title}
            maxLength={255}
            disabled={uploading}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="My CV"
            className={`${inputClass} max-sm:text-base`}
          />
        </Field>
      )}

      {error && <FormAlert>{error}</FormAlert>}

      <button
        type="button"
        disabled={!file || uploading || (Boolean(error) && !failed)}
        onClick={handleUpload}
        className={cn(primaryButtonClass, "min-h-12 disabled:cursor-not-allowed")}
      >
        {uploading ? (progress < 1 ? "Uploading…" : "Processing document…") : failed ? "↻ Retry upload" : "Upload Document"}
      </button>
    </div>
  );
}
