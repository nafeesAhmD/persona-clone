"use client";

import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { FormAlert } from "@/components/FormField";
import { VoiceReply } from "@/components/voice/VoiceReply";
import { ApiError, testVoice } from "@/lib/api";
import { beginBusy } from "@/lib/busy";
import { useMobileConfig } from "@/lib/mobileConfig";
import { isAbortError } from "@/lib/uploadWithProgress";
import { useVoiceRecorder, voiceSupportProblem } from "@/lib/useVoiceRecorder";
import {
  CLIP_MAX_SECONDS,
  FILE_ACCEPT,
  SUBMIT_BLOCK_MESSAGES,
  UNAVAILABLE_MESSAGE,
  canAddSample,
  cleanDuration,
  cloneStatusLabel,
  durationProgress,
  formatDuration,
  isAcceptedAudioFile,
  isCloningAvailable,
  providerCopy,
  submitBlock,
  totalDuration,
} from "@/lib/voiceClone";
import { createVoiceClone, deleteVoiceClone, getVoiceClone, setUseClonedVoice } from "@/lib/voiceCloneApi";
import { voiceErrorMessage } from "@/lib/voiceStates";
import type { VoiceCloneStatus } from "@/types/voiceClone";

interface Sample {
  id: string;
  blob: Blob;
  name: string;
  /** Object URL for playback (revoked on remove/unmount). */
  url: string;
  seconds: number | null;
  source: "mic" | "file";
}

interface Notice {
  kind: "success" | "error";
  text: string;
}

type Phase = "idle" | "uploading" | "processing";

const POLL_MS = 3000;

export const READING_SCRIPT = {
  english:
    "Hello, this is my own voice. I am recording this so my AI clone can speak the way I do. " +
    "I usually talk about my work, the people I help, and the things I care about. " +
    "On a quiet morning I like a cup of tea, a short walk, and time to plan my day. " +
    "If you have a question, ask me anything, and I will answer as clearly as I can.",
  urdu:
    "Assalam-o-Alaikum, yeh meri apni awaaz hai. Main yeh recording is liye kar raha/rahi hoon taa ke mera AI clone " +
    "bilkul meri tarah baat kar sake. Main aam taur par apne kaam, logon ki madad, aur un cheezon ke baare mein baat " +
    "karta/karti hoon jo mere liye ahem hain. Subah ki chai, thori si sair, aur din ki planning mujhe bohat pasand hai. " +
    "Agar aap ka koi sawal hai to zaroor poochiye, main asaan alfaaz mein jawab doon ga/gi.",
};

let nextId = 0;
const newId = () => `s${Date.now().toString(36)}${(nextId += 1)}`;

/** Length of an audio blob from its metadata (null when the browser can't tell, e.g. MediaRecorder WebM). */
function readDuration(url: string): Promise<number | null> {
  return new Promise((resolve) => {
    const audio = document.createElement("audio");
    let settled = false;
    const done = (value: number | null) => {
      if (settled) return;
      settled = true;
      audio.removeAttribute("src");
      resolve(value);
    };
    const timer = window.setTimeout(() => done(null), 5000);
    audio.preload = "metadata";
    audio.onloadedmetadata = () => {
      window.clearTimeout(timer);
      done(cleanDuration(audio.duration));
    };
    audio.onerror = () => {
      window.clearTimeout(timer);
      done(null);
    };
    audio.src = url;
  });
}

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.status === 403) {
    return err.message || "Not allowed. Check that voice consent is on for this clone and that your plan includes voice cloning.";
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

interface VoiceCloneSectionProps {
  cloneId: string;
  /** Voice consent on this clone (voice settings). Cloning needs it first. */
  voiceConsent: boolean;
  /** Voice turned on for the clone (needed for the test). */
  voiceEnabled: boolean;
  /** Called after the cloned voice was created, switched or deleted (voice settings change too). */
  onChanged?: () => void;
}

/** "My own voice": record or upload 1–2 minutes of speech and clone it (ElevenLabs or the local voice-clone service). */
export function VoiceCloneSection({ cloneId, voiceConsent, voiceEnabled, onChanged }: VoiceCloneSectionProps) {
  const { config } = useMobileConfig();
  const configFlag = (config.voice as { voice_cloning?: boolean }).voice_cloning;
  const [status, setStatus] = useState<VoiceCloneStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [cloneConsent, setCloneConsent] = useState(false);
  const [removeNoise, setRemoveNoise] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [replacing, setReplacing] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testAudio, setTestAudio] = useState<string | null>(null);
  // Only rendered in the browser (after the settings loaded), so this runs client-side.
  const [micProblem] = useState<string | null>(() => {
    const problem = voiceSupportProblem();
    return problem ? voiceErrorMessage(problem) : null;
  });

  const recorder = useVoiceRecorder(CLIP_MAX_SECONDS);
  const recordStart = useRef(0);
  const samplesRef = useRef<Sample[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const ids = { consent: useId(), noise: useId(), files: useId(), toggle: useId(), progress: useId(), script: useId() };

  useEffect(() => {
    samplesRef.current = samples;
  }, [samples]);

  const load = useCallback(() => {
    getVoiceClone(cloneId)
      .then((next) => {
        setStatus(next);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorText(err, "Couldn't load your cloned voice.")));
  }, [cloneId]);

  useEffect(load, [load]);

  // Free the playback URLs when leaving the page.
  useEffect(() => () => samplesRef.current.forEach((s) => URL.revokeObjectURL(s.url)), []);

  // The server answered "processing" (or it was already processing): check again until it settles.
  const serverProcessing = status?.status === "processing" && phase === "idle";
  useEffect(() => {
    if (!serverProcessing) return;
    const done = beginBusy();
    const timer = window.setInterval(() => {
      getVoiceClone(cloneId)
        .then((next) => {
          setStatus(next);
          if (next.status !== "processing") onChanged?.();
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
      done();
    };
  }, [serverProcessing, cloneId, onChanged]);

  const addSample = useCallback(async (blob: Blob, name: string, source: Sample["source"], knownSeconds: number | null) => {
    const url = URL.createObjectURL(blob);
    const id = newId();
    setSamples((list) => [...list, { id, blob, name, url, seconds: knownSeconds, source }]);
    if (knownSeconds === null || source === "file") {
      const measured = await readDuration(url);
      if (measured !== null) setSamples((list) => list.map((s) => (s.id === id ? { ...s, seconds: measured } : s)));
    }
  }, []);

  function removeSample(id: string) {
    setSamples((list) => {
      const gone = list.find((s) => s.id === id);
      if (gone) URL.revokeObjectURL(gone.url);
      return list.filter((s) => s.id !== id);
    });
  }

  function clearSamples() {
    samples.forEach((s) => URL.revokeObjectURL(s.url));
    setSamples([]);
  }

  const micClipName = (blob: Blob) => {
    const type = blob.type.split(";")[0];
    const ext = type === "audio/mp4" ? "m4a" : type === "audio/ogg" ? "ogg" : "webm";
    return `recording-${samplesRef.current.length + 1}.${ext}`;
  };

  async function toggleRecording() {
    setNotice(null);
    if (recorder.state === "recording") {
      const blob = await recorder.stopRecording();
      const seconds = (Date.now() - recordStart.current) / 1000;
      if (blob) await addSample(blob, micClipName(blob), "mic", seconds);
      return;
    }
    recordStart.current = Date.now();
    await recorder.startRecording((blob) => {
      // Reached the per-clip limit: keep the clip (nothing is uploaded until "Create my voice").
      if (blob) void addSample(blob, micClipName(blob), "mic", (Date.now() - recordStart.current) / 1000);
    });
  }

  function onFiles(list: FileList | null) {
    if (!list || !status) return;
    setNotice(null);
    const rejected: string[] = [];
    let count = samples.length;
    let skipped = 0;
    for (const file of Array.from(list)) {
      if (!isAcceptedAudioFile(file)) {
        rejected.push(file.name);
        continue;
      }
      if (!canAddSample(count, status.max_files)) {
        skipped += 1;
        continue;
      }
      count += 1;
      void addSample(file, file.name, "file", null);
    }
    const problems: string[] = [];
    if (rejected.length) problems.push(`Not an audio file we accept: ${rejected.join(", ")}. Use WebM, WAV, MP3, M4A or OGG.`);
    if (skipped) problems.push(`${skipped} file(s) skipped: at most ${status.max_files} samples.`);
    if (problems.length) setNotice({ kind: "error", text: problems.join(" ") });
    if (fileInput.current) fileInput.current.value = "";
  }

  async function createVoice() {
    if (!status) return;
    setNotice(null);
    setPhase("uploading");
    setProgress(0);
    const controller = new AbortController();
    abortRef.current = controller;
    const done = beginBusy();
    try {
      const next = await createVoiceClone(
        cloneId,
        samples.map((s) => ({ blob: s.blob, name: s.name })),
        cloneConsent,
        removeNoise,
        {
          signal: controller.signal,
          onProgress: setProgress,
          onUploaded: () => setPhase("processing"),
        },
      );
      setStatus(next);
      if (next.status === "ready") {
        clearSamples();
        setReplacing(false);
        setCloneConsent(false);
        setNotice({ kind: "success", text: "Your voice is ready. Turn on “Speak with my cloned voice” and test it." });
      } else if (next.status === "failed") {
        setNotice({ kind: "error", text: next.error || "Your voice could not be created. Try again with clearer recordings." });
      }
      onChanged?.();
    } catch (err) {
      if (isAbortError(err)) setNotice({ kind: "error", text: "Upload cancelled. Your samples are still here." });
      else setNotice({ kind: "error", text: errorText(err, "Your voice could not be created. Please try again.") });
    } finally {
      done();
      abortRef.current = null;
      setPhase("idle");
      setProgress(0);
      headingRef.current?.focus();
    }
  }

  async function switchClonedVoice(on: boolean) {
    setSwitching(true);
    setNotice(null);
    setTestAudio(null);
    try {
      setStatus(await setUseClonedVoice(cloneId, on));
      setNotice({ kind: "success", text: on ? "Your clone now speaks with your cloned voice." : "Cloned voice turned off. Your clone uses an AI voice." });
      onChanged?.();
    } catch (err) {
      setNotice({ kind: "error", text: errorText(err, "Couldn't change the voice. Please try again.") });
    } finally {
      setSwitching(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setNotice(null);
    setTestAudio(null);
    try {
      setTestAudio((await testVoice(cloneId, "Assalam-o-Alaikum, ye meri apni aawaz hai.")).audio_url);
    } catch (err) {
      setNotice({ kind: "error", text: errorText(err, "The voice test failed.") });
    } finally {
      setTesting(false);
    }
  }

  async function confirmDeleteVoice() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteVoiceClone(cloneId);
      setConfirmDelete(false);
      setTestAudio(null);
      setReplacing(false);
      setNotice({ kind: "success", text: providerCopy(status?.provider).deleted });
      load();
      onChanged?.();
      headingRef.current?.focus();
    } catch (err) {
      setDeleteError(errorText(err, "Couldn't delete the cloned voice. Please try again."));
    } finally {
      setDeleting(false);
    }
  }

  const wrapper = (children: ReactNode) => (
    <section id="my-voice" className="mt-6 scroll-mt-20 rounded-2xl border border-border bg-surface-raised p-4 sm:p-7" aria-labelledby="my-voice-heading">
      <h2 id="my-voice-heading" ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
        My own voice
      </h2>
      <p className="mt-1 text-sm text-muted">
        Let your clone speak with your real voice. Answers are still labelled as an AI-generated voice.
      </p>
      {children}
    </section>
  );

  if (loadError) {
    return wrapper(
      <div className="mt-4 space-y-3">
        <FormAlert>{loadError}</FormAlert>
        <button type="button" onClick={load} className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm hover:border-accent">
          Try again
        </button>
      </div>,
    );
  }
  if (!status) return wrapper(<p className="mt-4 text-sm text-muted" role="status">Loading your voice…</p>);

  const available = isCloningAvailable(configFlag, status.available);
  const copy = providerCopy(status.provider);
  const working = phase !== "idle" || status.status === "processing";
  const recording = recorder.state === "recording";
  const total = totalDuration(samples);
  const meter = durationProgress(total, status.min_seconds, status.max_seconds);
  const block = submitBlock({
    available,
    voiceConsent,
    cloneConsent,
    samples,
    minSeconds: status.min_seconds,
    maxSeconds: status.max_seconds,
    maxFiles: status.max_files,
    busy: working || recording || recorder.state === "requesting",
  });
  const roomForMore = canAddSample(samples.length, status.max_files);
  const showCollector = available && (status.status !== "ready" || replacing);

  const statusLine =
    phase === "uploading"
      ? `Uploading your samples… ${Math.round(progress * 100)}%`
      : phase === "processing"
        ? copy.creating
        : cloneStatusLabel(status.status, status.use_cloned_voice);

  return wrapper(
    <>
      <p className="mt-3 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-accent-soft">
        <span aria-hidden="true">🔊 </span>AI-generated voice: even when it sounds like you, people are told it is AI.
      </p>

      {!available && (
        <div className="mt-4">
          <FormAlert>{UNAVAILABLE_MESSAGE}</FormAlert>
        </div>
      )}

      {available && !voiceConsent && (
        <div className="mt-4">
          <FormAlert>Voice consent on this clone must be on first. Give it in “Voice Consent” above.</FormAlert>
        </div>
      )}

      <div className="mt-4 rounded-xl border border-border px-4 py-3 text-sm">
        <span className="text-muted">Status: </span>
        <span role="status" aria-live="polite" className="font-medium">
          {statusLine}
        </span>
        {status.status === "failed" && status.error && phase === "idle" && (
          <span className="mt-1 block text-rose-300">
            <span aria-hidden="true">⚠ </span>
            {status.error}
          </span>
        )}
        {phase === "uploading" && (
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-border" aria-hidden="true">
            <div className="h-full bg-accent transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
        )}
      </div>

      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      {available && status.status === "ready" && !replacing && (
        <div className="mt-5 space-y-4">
          <label htmlFor={ids.toggle} className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              id={ids.toggle}
              type="checkbox"
              role="switch"
              aria-checked={status.use_cloned_voice}
              checked={status.use_cloned_voice}
              disabled={switching || !voiceConsent}
              onChange={(e) => void switchClonedVoice(e.target.checked)}
              className="size-5 shrink-0 accent-accent"
            />
            <span>
              <span className="font-medium">Speak with my cloned voice</span>
              <span className="block text-xs text-muted">
                {switching ? "Saving…" : status.use_cloned_voice ? "On: chat answers, videos and live calls use your voice." : "Off: an AI voice is used."}
              </span>
            </span>
          </label>

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <button
              type="button"
              onClick={runTest}
              disabled={testing || !voiceEnabled || !status.use_cloned_voice}
              className="min-h-11 rounded-xl border border-accent/50 px-4 py-2 text-sm text-accent-soft hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {testing ? copy.generating : "Test my voice"}
            </button>
            <button
              type="button"
              onClick={() => {
                setReplacing(true);
                setNotice(null);
              }}
              className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
            >
              Replace (record again)
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="min-h-11 rounded-xl border border-rose-500/40 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10 sm:ml-auto"
            >
              Delete my cloned voice
            </button>
          </div>
          {(!voiceEnabled || !status.use_cloned_voice) && (
            <p className="text-xs text-muted">
              To test: turn on “Speak with my cloned voice”{voiceEnabled ? "" : " and turn Voice on in Voice Settings (then save)"}.
            </p>
          )}
          {testAudio && <VoiceReply key={testAudio} audioUrl={testAudio} autoPlay label="Play my voice" />}
        </div>
      )}

      {showCollector && (
        <div className="mt-5 space-y-5">
          {replacing && (
            <p className="text-sm text-muted">
              Record new samples. Creating the new voice replaces (and deletes) the old one.{" "}
              <button
                type="button"
                onClick={() => {
                  setReplacing(false);
                  clearSamples();
                }}
                className="inline-flex min-h-11 items-center text-accent-soft underline md:min-h-0"
              >
                Keep my current voice
              </button>
            </p>
          )}

          <div className="space-y-2 text-sm">
            <h3 className="font-medium">How to record a good sample</h3>
            <ul className="list-disc space-y-1 pl-5 text-muted">
              <li>
                Record 1–2 minutes of natural speech in total (at least {formatDuration(status.min_seconds)}, at most{" "}
                {formatDuration(status.max_seconds)}).
              </li>
              <li>Use a quiet room. Only you should be speaking — no music, TV or other voices.</li>
              <li>Speak the language(s) your clone will speak (Urdu and/or English), at your normal pace.</li>
              <li>Several short clips are fine (each up to {CLIP_MAX_SECONDS} seconds, at most {status.max_files} samples).</li>
            </ul>
            <p className="text-xs text-muted">
              {copy.privacy}
            </p>
          </div>

          <details className="rounded-xl border border-border px-4 py-3 text-sm">
            <summary className="flex min-h-11 cursor-pointer items-center font-medium">Suggested text to read aloud</summary>
            <div id={ids.script} className="mt-2 space-y-3 break-words text-gray-200">
              <p lang="en">{READING_SCRIPT.english}</p>
              <p lang="ur-Latn">{READING_SCRIPT.urdu}</p>
            </div>
          </details>

          <div className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <button
                type="button"
                onClick={() => void toggleRecording()}
                disabled={working || recorder.state === "requesting" || (!recording && !roomForMore) || micProblem !== null || !voiceConsent}
                aria-pressed={recording}
                className={`min-h-11 rounded-xl px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                  recording ? "bg-rose-600 text-white hover:bg-rose-500" : "border border-accent/50 text-accent-soft hover:bg-accent/10"
                }`}
              >
                {recorder.state === "requesting"
                  ? "Allow the microphone…"
                  : recording
                    ? `■ Stop recording (${formatDuration(recorder.seconds)} / ${formatDuration(CLIP_MAX_SECONDS)})`
                    : "● Record a clip"}
              </button>
              <label
                htmlFor={ids.files}
                className={`inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 py-2 text-sm ${
                  working || recording || !roomForMore || !voiceConsent ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:border-accent"
                }`}
              >
                Upload audio files
              </label>
              <input
                ref={fileInput}
                id={ids.files}
                type="file"
                accept={FILE_ACCEPT}
                multiple
                disabled={working || recording || !roomForMore || !voiceConsent}
                onChange={(e) => onFiles(e.target.files)}
                className="sr-only"
              />
            </div>
            {recording && (
              <p className="text-xs text-muted" role="status">
                Recording… it stops by itself at {CLIP_MAX_SECONDS} seconds.
              </p>
            )}
            {micProblem && <p className="text-xs text-amber-300">Microphone: {micProblem} You can still upload audio files.</p>}
            {recorder.error && <FormAlert>{recorder.error}</FormAlert>}
          </div>

          {samples.length > 0 && (
            <ul className="space-y-3" aria-label="Your voice samples">
              {samples.map((sample, index) => (
                <li key={sample.id} className="rounded-xl border border-border p-3">
                  <div className="flex items-start justify-between gap-3 text-sm">
                    <span className="min-w-0 break-words">
                      <span className="font-medium">
                        {index + 1}. {sample.source === "mic" ? "Recording" : sample.name}
                      </span>
                      <span className="block text-xs text-muted">
                        {sample.seconds !== null ? formatDuration(sample.seconds) : "Length unknown"}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => removeSample(sample.id)}
                      disabled={working}
                      aria-label={`Remove sample ${index + 1}`}
                      className="min-h-11 min-w-11 shrink-0 rounded-lg border border-border px-3 text-xs text-rose-300 hover:border-rose-400 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </div>
                  <audio controls preload="metadata" src={sample.url} className="mt-2 w-full max-w-full" aria-label={`Play sample ${index + 1}`} />
                </li>
              ))}
            </ul>
          )}

          <div>
            <div className="flex flex-wrap justify-between gap-x-3 text-xs text-muted">
              <span id={ids.progress}>Total length</span>
              <span>
                {samples.length} / {status.max_files} samples
              </span>
            </div>
            <div
              role="progressbar"
              aria-labelledby={ids.progress}
              aria-valuemin={0}
              aria-valuemax={Math.round(status.max_seconds)}
              aria-valuenow={Math.round(total.seconds)}
              aria-valuetext={meter.label}
              className="relative mt-1 h-3 overflow-hidden rounded-full bg-border"
            >
              <div
                className={`h-full ${meter.level === "ok" ? "bg-emerald-500" : meter.level === "long" ? "bg-rose-500" : "bg-amber-400"}`}
                style={{ width: `${meter.percent}%` }}
              />
              {/* Marker for the minimum length. */}
              <div
                aria-hidden="true"
                className="absolute inset-y-0 w-0.5 bg-white/70"
                style={{ left: `${Math.min(100, (status.min_seconds / Math.max(1, status.max_seconds)) * 100)}%` }}
              />
            </div>
            <p className="mt-1 text-sm" aria-live="polite">
              <span aria-hidden="true">{meter.level === "ok" ? "✓ " : meter.level === "long" ? "⚠ " : "• "}</span>
              {meter.label}
            </p>
          </div>

          <label htmlFor={ids.noise} className="flex min-h-11 cursor-pointer items-start gap-3 text-sm">
            <input
              id={ids.noise}
              type="checkbox"
              checked={removeNoise}
              onChange={(e) => setRemoveNoise(e.target.checked)}
              disabled={working}
              className="mt-0.5 size-5 shrink-0 accent-accent"
            />
            <span>
              Remove background noise
              <span className="block text-xs text-muted">Only if your recording has noise; it can lower quality on clean audio.</span>
            </span>
          </label>

          <label htmlFor={ids.consent} className="flex min-h-11 cursor-pointer items-start gap-3 text-sm">
            <input
              id={ids.consent}
              type="checkbox"
              required
              aria-required="true"
              checked={cloneConsent}
              onChange={(e) => setCloneConsent(e.target.checked)}
              disabled={working}
              className="mt-0.5 size-5 shrink-0 accent-accent"
            />
            <span>
              This is my own voice, or I have the speaker&apos;s explicit permission to clone it.
              <span className="block text-xs text-muted">Required. Voice consent on this clone must already be on.</span>
            </span>
          </label>

          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => void createVoice()}
              disabled={block !== null}
              aria-describedby={block ? `${ids.consent}-why` : undefined}
              className="min-h-12 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-11"
            >
              {phase === "uploading"
                ? `Uploading… ${Math.round(progress * 100)}%`
                : phase === "processing"
                  ? "Creating your voice…"
                  : replacing
                    ? "Create my new voice"
                    : "Create my voice"}
            </button>
            {phase === "uploading" && (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="min-h-11 rounded-xl border border-border px-4 py-2 text-sm hover:border-accent"
              >
                Cancel upload
              </button>
            )}
          </div>
          {block && block !== "busy" && (
            <p id={`${ids.consent}-why`} className="text-xs text-muted">
              {SUBMIT_BLOCK_MESSAGES[block]}
            </p>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Delete your cloned voice?"
        message={copy.deleteConfirm}
        confirmLabel="Delete my voice"
        busyLabel="Deleting…"
        busy={deleting}
        error={deleteError}
        onConfirm={() => void confirmDeleteVoice()}
        onCancel={() => {
          setConfirmDelete(false);
          setDeleteError(null);
        }}
      />
    </>,
  );
}
