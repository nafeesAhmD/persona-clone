"use client";

import { useEffect, useState } from "react";

import { getAvatarJob } from "@/lib/api";
import { postFormWithProgress, type UploadOptions } from "@/lib/uploadWithProgress";
import type { AvatarJob, CloneAvatar } from "@/types/avatar";

const POLL_MS = 2000;
const GIVE_UP_MS = 5 * 60 * 1000; // never poll forever

const FINISHED = new Set(["completed", "failed", "cancelled"]);

/** Same limits as the avatar upload on the server (JPG/PNG/WebP, 10 MB). */
export const AVATAR_MAX_MB = 10;
export const AVATAR_TYPES = ["image/jpeg", "image/png", "image/webp"];

/** Polls a talking-avatar video job until it finishes (or gives up after 5 minutes). */
export function useAvatarJob(cloneId: string, jobId: string | null) {
  const [job, setJob] = useState<AvatarJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: number | undefined;
    const started = Date.now();

    async function poll() {
      try {
        const current = await getAvatarJob(cloneId, jobId as string);
        if (stopped) return;
        setJob(current);
        setError(null);
        if (FINISHED.has(current.status)) return;
      } catch (err) {
        if (stopped) return;
        setError(err instanceof Error ? err.message : "Couldn't check the video.");
      }
      if (Date.now() - started > GIVE_UP_MS) {
        setError("The video is taking too long. Please try again later.");
        return;
      }
      timer = window.setTimeout(poll, POLL_MS);
    }

    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [cloneId, jobId]);

  return { job, error };
}

/** The four states shown to people: queued, processing, completed, failed. */
export function jobPhase(job: AvatarJob | null, gaveUp = false): "queued" | "processing" | "completed" | "failed" {
  if (gaveUp && (!job || !FINISHED.has(job.status))) return "failed";
  if (!job || job.status === "queued") return "queued";
  if (job.status === "processing") return "processing";
  if (job.status === "completed" && !job.expired) return "completed";
  return "failed";
}

/** What to show for a job's progress. */
export function jobStage(job: AvatarJob | null): string {
  if (!job || job.status === "queued") return "Queued…";
  if (job.status === "processing") {
    if (job.progress < 15) return "Processing…";
    if (job.progress < 80) return "Generating video…";
    return "Almost ready…";
  }
  if (job.status === "completed") return job.expired ? "This video has expired." : "Completed";
  if (job.status === "cancelled") return "Cancelled";
  return "Failed";
}

/** A friendly reason a picked image can't be used, or null. Checked before uploading. */
export function validateAvatarImage(file: { type: string; size: number }, maxMb = AVATAR_MAX_MB): string | null {
  // Phones may hand over HEIC photos; the server only reads JPG, PNG and WebP.
  if (file.type && !AVATAR_TYPES.includes(file.type)) {
    return "This image type isn't supported. Use a JPG, PNG or WebP photo (on iPhone: Settings › Camera › Formats › Most Compatible).";
  }
  if (file.size === 0) return "The image is empty.";
  if (file.size > maxMb * 1024 * 1024) return `The image is too large. Maximum allowed size is ${maxMb} MB.`;
  return null;
}

/** Uploads an avatar image with progress (same endpoint as uploadAvatar in lib/api). */
export function uploadAvatarWithProgress(cloneId: string, image: File, options: UploadOptions = {}): Promise<CloneAvatar> {
  const form = new FormData();
  form.append("image", image);
  return postFormWithProgress<CloneAvatar>(`/api/clones/${encodeURIComponent(cloneId)}/avatar`, form, options);
}
