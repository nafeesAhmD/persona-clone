/**
 * Pure rules for the personal voice clone UI (no React, no fetch) so they can be tested
 * with node --test. See docs/voice-clone/contract.md.
 */

export type CloneState = "none" | "processing" | "ready" | "failed";

/** A voice sample in the list: a mic recording or an uploaded file. */
export interface SampleInfo {
  /** Length in seconds; null when the browser couldn't read it (the server still checks). */
  seconds: number | null;
}

/** Per-clip mic limit (matches the server's per-recording audio limit). */
export const CLIP_MAX_SECONDS = 60;

/** Formats the server accepts (contract: WebM/WAV/MP3/M4A/OGG). */
export const ACCEPTED_EXTENSIONS = ["webm", "wav", "mp3", "m4a", "ogg", "oga", "opus", "mp4", "aac", "mpeg"] as const;

const ACCEPTED_MIME = new Set([
  "audio/webm",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/vnd.wave",
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/x-m4a",
  "audio/m4a",
  "audio/aac",
  "audio/ogg",
  "audio/opus",
  "video/webm", // some browsers label audio-only WebM this way
]);

/** Value for <input type="file" accept>. */
export const FILE_ACCEPT = "audio/*,.webm,.wav,.mp3,.m4a,.ogg,.opus";

/** Whether a chosen file looks like audio the server accepts (by MIME type, else extension). */
export function isAcceptedAudioFile(file: { name: string; type: string }): boolean {
  const type = file.type.split(";")[0].trim().toLowerCase();
  if (type && ACCEPTED_MIME.has(type)) return true;
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  if (file.name.includes(".") && (ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) {
    // Unknown or empty MIME type with a known extension: accept, unless it is clearly not audio.
    return !type || type === "application/octet-stream" || type.startsWith("audio/") || type.startsWith("video/");
  }
  return false;
}

/** A usable duration from an <audio> element (MediaRecorder WebM often reports Infinity). */
export function cleanDuration(value: number | null | undefined): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
  return value;
}

export interface DurationTotal {
  /** Sum of the known lengths, in seconds. */
  seconds: number;
  /** Samples whose length is unknown. */
  unknown: number;
}

export function totalDuration(samples: SampleInfo[]): DurationTotal {
  let seconds = 0;
  let unknown = 0;
  for (const sample of samples) {
    const s = cleanDuration(sample.seconds);
    if (s === null) unknown += 1;
    else seconds += s;
  }
  return { seconds, unknown };
}

/** "1:05" */
export function formatDuration(total: number): string {
  const safe = Math.max(0, Math.round(total));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

export type DurationLevel = "empty" | "short" | "ok" | "long";

export interface DurationProgress {
  level: DurationLevel;
  /** 0..100 for the progress bar (100 = the maximum). */
  percent: number;
  /** Text shown next to the bar, so the state is never color-only. */
  label: string;
}

export function durationProgress(total: DurationTotal, minSeconds: number, maxSeconds: number): DurationProgress {
  const { seconds, unknown } = total;
  const max = Math.max(1, maxSeconds);
  const percent = Math.min(100, Math.round((seconds / max) * 100));
  const range = `${formatDuration(minSeconds)}–${formatDuration(maxSeconds)}`;
  const unknownNote = unknown > 0 ? ` (+${unknown} of unknown length, checked by the server)` : "";
  if (seconds <= 0 && unknown === 0) {
    return { level: "empty", percent: 0, label: `No samples yet. Needed: ${range}.` };
  }
  if (seconds > maxSeconds) {
    return { level: "long", percent: 100, label: `${formatDuration(seconds)} recorded: too long, the maximum is ${formatDuration(maxSeconds)}. Remove a sample.` };
  }
  if (seconds < minSeconds && unknown === 0) {
    return {
      level: "short",
      percent,
      label: `${formatDuration(seconds)} recorded: ${formatDuration(minSeconds - seconds)} more needed (minimum ${formatDuration(minSeconds)}).`,
    };
  }
  return { level: "ok", percent, label: `${formatDuration(seconds)} recorded${unknownNote}. Good: ${range} needed.` };
}

export interface SubmitInput {
  available: boolean;
  /** Voice consent on the clone (voice settings). */
  voiceConsent: boolean;
  /** "This is my own voice…" checkbox. */
  cloneConsent: boolean;
  samples: SampleInfo[];
  minSeconds: number;
  maxSeconds: number;
  maxFiles: number;
  busy?: boolean;
}

export type SubmitBlock =
  | "unavailable"
  | "voice_consent"
  | "busy"
  | "no_samples"
  | "too_many_files"
  | "too_short"
  | "too_long"
  | "clone_consent";

export const UNAVAILABLE_MESSAGE =
  "Voice cloning isn't set up on this server (ELEVENLABS_API_KEY or the local voice-clone service).";

export type CloneProvider = "elevenlabs" | "local" | null | undefined;

export interface ProviderCopy {
  /** Privacy note shown with the recording tips. */
  privacy: string;
  /** Status line while the voice is being created. */
  creating: string;
  /** Notice after the cloned voice was deleted. */
  deleted: string;
  /** Text of the delete confirmation. */
  deleteConfirm: string;
  /** Button text while a test of the voice is being generated. */
  generating: string;
}

/** Texts that depend on where the voice is cloned (VoiceCloneStatus.provider). */
export function providerCopy(provider: CloneProvider): ProviderCopy {
  const back = "Your clone goes back to an AI voice. You can record a new one later.";
  if (provider === "elevenlabs") {
    return {
      privacy: "Privacy: your recordings are sent to ElevenLabs to create the voice. This app doesn't store them.",
      creating: "Creating your voice with ElevenLabs… this can take up to a minute.",
      deleted: "Your cloned voice was deleted here and at ElevenLabs.",
      deleteConfirm: `Your cloned voice will be deleted from this app and from ElevenLabs. ${back}`,
      generating: "Generating…",
    };
  }
  if (provider === "local") {
    return {
      privacy:
        "Your recordings are processed on this server by an open-source model (Chatterbox, MIT). Nothing is sent to an outside company. Speech is slower on a computer without a GPU; Urdu is spoken with a Hindi accent model.",
      creating: "Creating your voice on this server… this can take a minute or two.",
      deleted: "Your cloned voice was deleted from this server.",
      deleteConfirm: `Your cloned voice will be deleted from this app and from the voice service on this server. ${back}`,
      generating: "Generating… (1–2 minutes on this server)",
    };
  }
  return {
    privacy: "Privacy: your recordings are only used to create the voice. This app doesn't store them.",
    creating: "Creating your voice… this can take a minute or two.",
    deleted: "Your cloned voice was deleted.",
    deleteConfirm: `Your cloned voice will be deleted. ${back}`,
    generating: "Generating…",
  };
}

export const SUBMIT_BLOCK_MESSAGES: Record<SubmitBlock, string> = {
  unavailable: UNAVAILABLE_MESSAGE,
  voice_consent: "Give voice consent on this clone first (Voice Consent above).",
  busy: "Please wait until the current step finishes.",
  no_samples: "Record or upload at least one sample.",
  too_many_files: "Too many samples. Remove some.",
  too_short: "Add more speech: the samples are shorter than the minimum.",
  too_long: "The samples are longer than the maximum. Remove one.",
  clone_consent: "Tick the box to confirm it is your own voice or that you have permission.",
};

/** Why "Create my voice" is disabled, or null when it can be pressed. */
export function submitBlock(input: SubmitInput): SubmitBlock | null {
  if (!input.available) return "unavailable";
  if (!input.voiceConsent) return "voice_consent";
  if (input.busy) return "busy";
  if (input.samples.length === 0) return "no_samples";
  if (input.samples.length > input.maxFiles) return "too_many_files";
  const total = totalDuration(input.samples);
  if (total.seconds > input.maxSeconds) return "too_long";
  // Unknown lengths can't be checked here: the server checks the real total.
  if (total.unknown === 0 && total.seconds < input.minSeconds) return "too_short";
  if (!input.cloneConsent) return "clone_consent";
  return null;
}

export function canSubmit(input: SubmitInput): boolean {
  return submitBlock(input) === null;
}

/** Whether another sample can be added (recorded or uploaded). */
export function canAddSample(count: number, maxFiles: number): boolean {
  return count < maxFiles;
}

export function cloneStatusLabel(status: CloneState, useClonedVoice = false): string {
  switch (status) {
    case "ready":
      return useClonedVoice ? "Ready: your clone speaks with your cloned voice" : "Ready: cloned voice is off (using an AI voice)";
    case "processing":
      return "Creating your voice…";
    case "failed":
      return "Failed: your voice could not be created";
    default:
      return "Not created yet";
  }
}

/**
 * Whether cloning is offered: the mobile config switch (voice.voice_cloning) when the
 * server sends it, else the clone status `available`.
 */
export function isCloningAvailable(configFlag: boolean | undefined, statusAvailable: boolean | undefined): boolean {
  if (typeof configFlag === "boolean" && !configFlag) return false;
  if (typeof statusAvailable === "boolean") return statusAvailable;
  return configFlag === true;
}

// --- "Make it look and sound real" checklist ---

export type RealismState = "done" | "partial" | "todo" | "unavailable" | "unknown";

export interface RealismItem {
  key: "voice" | "videos" | "live";
  title: string;
  state: RealismState;
  detail: string;
  /** Path under /clone/{id}. */
  path: string;
  linkLabel: string;
  serverHint: string;
}

export interface RealismInput {
  /** null = couldn't load. */
  voice: { available: boolean; status: CloneState; use_cloned_voice: boolean } | null;
  avatar: { lipsync_provider: string | null } | null;
  live: { available: boolean; face_ready: boolean; face_status: string } | null;
}

export const REALISM_STATE_LABELS: Record<RealismState, string> = {
  done: "Done",
  partial: "Almost",
  todo: "To do",
  unavailable: "Not set up on server",
  unknown: "Unknown",
};

export function realismChecklist(input: RealismInput): RealismItem[] {
  const { voice, avatar, live } = input;

  let voiceState: RealismState = "unknown";
  let voiceDetail = "Couldn't check the cloned voice right now.";
  if (voice) {
    if (!voice.available) {
      voiceState = "unavailable";
      voiceDetail = "Voice cloning isn't set up on this server.";
    } else if (voice.status === "ready" && voice.use_cloned_voice) {
      voiceState = "done";
      voiceDetail = "Your cloned voice is created and in use.";
    } else if (voice.status === "ready") {
      voiceState = "partial";
      voiceDetail = "Your cloned voice is created but turned off.";
    } else if (voice.status === "processing") {
      voiceState = "partial";
      voiceDetail = "Your cloned voice is being created.";
    } else {
      voiceState = "todo";
      voiceDetail = voice.status === "failed" ? "The last attempt failed. Record again." : "Record 1–2 minutes of your voice.";
    }
  }

  let videoState: RealismState = "unknown";
  let videoDetail = "Couldn't check the avatar settings right now.";
  if (avatar) {
    if (avatar.lipsync_provider === "fal") {
      videoState = "done";
      videoDetail = "Realistic talking videos are on (fal).";
    } else {
      videoState = "unavailable";
      videoDetail = avatar.lipsync_provider
        ? `Videos use "${avatar.lipsync_provider}", not the realistic provider.`
        : "Talking videos aren't set up on this server.";
    }
  }

  let liveState: RealismState = "unknown";
  let liveDetail = "Couldn't check the live video face right now.";
  if (live) {
    if (!live.available) {
      liveState = "unavailable";
      liveDetail = "Live video calls aren't set up on this server.";
    } else if (live.face_ready) {
      liveState = "done";
      liveDetail = "Your live call face is ready.";
    } else if (live.face_status === "processing") {
      liveState = "partial";
      liveDetail = "Your live call face is being prepared.";
    } else {
      liveState = "todo";
      liveDetail = live.face_status === "failed" ? "Preparing the face failed. Try again." : "Prepare the live call face from your avatar photo.";
    }
  }

  return [
    {
      key: "voice",
      title: "Your own voice",
      state: voiceState,
      detail: voiceDetail,
      path: "voice#my-voice",
      linkLabel: "Set up my voice",
      serverHint: "Server needs ELEVENLABS_API_KEY or the local voice-clone service (LOCAL_VOICE_CLONE_URL).",
    },
    {
      key: "videos",
      title: "Realistic avatar videos",
      state: videoState,
      detail: videoDetail,
      path: "avatar",
      linkLabel: "Avatar settings",
      serverHint: "Server needs FAL_API_KEY and LIPSYNC_PROVIDER=fal.",
    },
    {
      key: "live",
      title: "Live video call face",
      state: liveState,
      detail: liveDetail,
      path: "avatar#live-avatar",
      linkLabel: "Live call setup",
      serverHint: "Server needs SIMLI_API_KEY.",
    },
  ];
}
