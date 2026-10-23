"use client";

import { API_URL, ApiError } from "@/lib/api";

export interface UploadOptions {
  /** 0..1 while the body is being sent. */
  onProgress?: (fraction: number) => void;
  /** The whole body reached the server; it is now processing (e.g. transcribing). */
  onUploaded?: () => void;
  signal?: AbortSignal;
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((d: { msg?: string }) => d?.msg)
      .filter(Boolean)
      .join("; ") || fallback;
  }
  return fallback;
}

/**
 * POSTs multipart form data with upload progress (fetch can't report it). Sends the
 * session cookie like apiFetch. Rejects with ApiError (no status = never reached the
 * server) or a DOMException named "AbortError" when cancelled.
 */
export function postFormWithProgress<T>(path: string, form: FormData, options: UploadOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (options.signal?.aborted) {
      reject(new DOMException("Cancelled", "AbortError"));
      return;
    }
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}${path}`);
    request.withCredentials = true;
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total);
    };
    request.upload.onload = () => {
      options.onProgress?.(1);
      options.onUploaded?.();
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(request.response as T);
        return;
      }
      const detail = (request.response as { detail?: unknown } | null)?.detail;
      reject(new ApiError(detailMessage(detail, `Request failed (${request.status})`), request.status));
    };
    request.onerror = () => reject(new ApiError("Could not reach the API server"));
    request.ontimeout = () => reject(new ApiError("The request timed out"));
    const abort = () => {
      request.abort();
      reject(new DOMException("Cancelled", "AbortError"));
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    request.onloadend = () => options.signal?.removeEventListener("abort", abort);
    request.send(form);
  });
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
