"use client";

import { apiFetch, audioExtension } from "@/lib/api";
import { postFormWithProgress, type UploadOptions } from "@/lib/uploadWithProgress";
import type { VoiceCloneStatus } from "@/types/voiceClone";

/** Owner-only endpoints under /api/clones/{id}/voice/clone (docs/voice-clone/contract.md). */
const clonePath = (cloneId: string) => `/api/clones/${encodeURIComponent(cloneId)}/voice/clone`;

/** One sample sent to the server: a mic recording (Blob) or a chosen file. */
export interface VoiceSampleUpload {
  blob: Blob;
  /** File name to send (the server reads the extension). */
  name?: string;
}

export function getVoiceClone(cloneId: string): Promise<VoiceCloneStatus> {
  return apiFetch<VoiceCloneStatus>(clonePath(cloneId), { cache: "no-store" });
}

/**
 * Creates (or replaces) the cloned voice. Multipart: files[] + consent + remove_background_noise.
 * Uses XMLHttpRequest so the upload can report progress; `onUploaded` fires once the
 * audio reached the server and ElevenLabs is processing it.
 */
export function createVoiceClone(
  cloneId: string,
  files: VoiceSampleUpload[],
  consent: boolean,
  removeBackgroundNoise: boolean,
  options: UploadOptions = {},
): Promise<VoiceCloneStatus> {
  const form = new FormData();
  files.forEach((file, index) => {
    const name = file.name || `sample-${index + 1}.${audioExtension(file.blob.type)}`;
    form.append("files", file.blob, name);
  });
  form.append("consent", consent ? "true" : "false");
  form.append("remove_background_noise", removeBackgroundNoise ? "true" : "false");
  return postFormWithProgress<VoiceCloneStatus>(clonePath(cloneId), form, options);
}

export function setUseClonedVoice(cloneId: string, useClonedVoice: boolean): Promise<VoiceCloneStatus> {
  return apiFetch<VoiceCloneStatus>(clonePath(cloneId), {
    method: "PATCH",
    body: JSON.stringify({ use_cloned_voice: useClonedVoice }),
  });
}

export function deleteVoiceClone(cloneId: string): Promise<void> {
  return apiFetch<void>(clonePath(cloneId), { method: "DELETE" });
}
