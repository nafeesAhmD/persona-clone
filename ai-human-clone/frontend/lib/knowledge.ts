import type { DocumentListItem, DocumentStatus, IndexingStatus } from "@/types/clone";

// Mirrors the backend defaults (MAX_UPLOAD_SIZE_MB, allowed types) for instant
// feedback. The API is the real gatekeeper and re-checks everything.
export const MAX_UPLOAD_MB = 10;
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];
export const ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
];
/** Extensions plus MIME types: some mobile pickers (Android Files, iOS Files) filter by MIME type only. */
export const ACCEPT_ATTRIBUTE = [...ACCEPTED_EXTENSIONS, ...ACCEPTED_MIME_TYPES].join(",");
export const MANUAL_MIN_CHARACTERS = 20;
export const MANUAL_MAX_CHARACTERS = 50_000;

export const STATUS_LABELS: Record<DocumentStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

export const INDEXING_LABELS: Record<IndexingStatus, string> = {
  not_indexed: "Not indexed",
  indexing: "Indexing",
  indexed: "Indexed",
  indexing_failed: "Indexing failed",
};

/**
 * Checked before uploading (the API re-checks). `maxMb` is the server's upload limit when
 * known (e.g. from the mobile config), otherwise the default.
 */
export function validateUploadFile(
  file: { name: string; size: number; type?: string },
  maxMb: number = MAX_UPLOAD_MB,
): string | null {
  const name = displayFileName(file.name);
  const extension = name.includes(".") ? `.${name.split(".").pop()!.toLowerCase()}` : "";
  const type = (file.type ?? "").split(";")[0].trim().toLowerCase();
  const knownExtension = ACCEPTED_EXTENSIONS.includes(extension);
  // A known extension decides; without one, fall back to the MIME type the picker reported.
  if (extension ? !knownExtension : !ACCEPTED_MIME_TYPES.includes(type)) {
    return "Unsupported file type. Upload a PDF, DOCX or TXT file.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > maxMb * 1024 * 1024) return `File is too large. Maximum allowed size is ${maxMb} MB.`;
  return null;
}

/** Only the file's own name: never a folder or device path (some browsers include one). */
export function displayFileName(name: string | null | undefined): string {
  if (!name) return "";
  const parts = name.split(/[\\/]/);
  return parts[parts.length - 1] || name;
}

const PATH_PATTERN = /(?:[A-Za-z]:\\|\\\\|\/(?:home|Users|var|tmp|app|srv|opt|usr|mnt|data|private)\/)[^\s"'<>,;:]*/g;

/** Hides server or device file-system paths that may appear in an error message. */
export function stripPaths(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(PATH_PATTERN, "[file]");
}

/** Case-insensitive search over a document list (title, file name, type). */
export function filterDocuments<T extends Pick<DocumentListItem, "title" | "original_filename" | "file_type">>(
  documents: T[],
  query: string,
): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return documents;
  return documents.filter((document) =>
    [document.title, displayFileName(document.original_filename), document.file_type ?? ""]
      .some((value) => value.toLowerCase().includes(needle)),
  );
}

/** Documents still being worked on by the server (worth checking again shortly). */
export function isDocumentBusy(document: Pick<DocumentListItem, "status" | "indexing_status">): boolean {
  return document.status === "pending" || document.status === "processing" || document.indexing_status === "indexing";
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

export function sourceLabel(document: Pick<DocumentListItem, "source_type" | "file_type">): string {
  if (document.source_type === "manual_text") return "Manual Knowledge";
  return document.file_type ? document.file_type.toUpperCase() : "File";
}

export function sourceIcon(document: Pick<DocumentListItem, "source_type">): string {
  return document.source_type === "manual_text" ? "📝" : "📄";
}
