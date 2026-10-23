"use client";

import Link from "next/link";
import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiErrorState } from "@/components/ApiErrorState";
import { AvatarVideo } from "@/components/avatar/AvatarVideo";
import { ProtectedImage } from "@/components/avatar/ProtectedImage";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Field, FormAlert, inputClass } from "@/components/FormField";
import { LiveAvatarSetup } from "@/components/live/LiveAvatarSetup";
import { StatusMessage } from "@/components/StatusMessage";
import {
  createTestVideo,
  deleteAvatar,
  generateAvatar,
  getAvatarSettings,
  getClone,
  updateAvatarSettings,
} from "@/lib/api";
import { isAbortError } from "@/lib/uploadWithProgress";
import { AVATAR_MAX_MB, uploadAvatarWithProgress, validateAvatarImage } from "@/lib/useAvatarJob";
import { cn } from "@/lib/utils";
import type { AvatarSettings, AvatarStyle, CloneAvatar } from "@/types/avatar";
import type { CloneProfile } from "@/types/clone";

const STATUS_TEXT: Record<CloneAvatar["status"], string> = {
  ready: "✓ Ready",
  processing: "⏳ Processing",
  pending: "⏳ Pending",
  failed: "⚠ Failed",
};

const STATUS_STYLES: Record<CloneAvatar["status"], string> = {
  ready: "border-emerald-500/40 text-emerald-300",
  processing: "border-amber-400/40 text-amber-300",
  pending: "border-amber-400/40 text-amber-300",
  failed: "border-rose-500/40 text-rose-300",
};

const DEFAULT_STYLE: AvatarStyle = {
  skin: "#b98a68",
  hair: "#1f1a17",
  hair_style: "short",
  background: "#3b4a8f",
  shirt: "#2d6a8a",
};

interface Notice {
  kind: "success" | "error";
  text: string;
}

export function AvatarSettingsPanel({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneProfile | null>(null);
  const [settings, setSettings] = useState<AvatarSettings | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [consentChecked, setConsentChecked] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [style, setStyle] = useState<AvatarStyle>(DEFAULT_STYLE);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [testText, setTestText] = useState("Hello, I am an AI Clone.");
  const [testJob, setTestJob] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);
  /** Upload progress 0..1, then "processing" while the server checks the image. */
  const [uploadProgress, setUploadProgress] = useState<number | "processing" | null>(null);
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const uploadAbort = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    Promise.all([getClone(cloneId), getAvatarSettings(cloneId)])
      .then(([cloneData, avatar]) => {
        setClone(cloneData);
        setSettings(avatar);
        setConsentChecked(avatar.avatar_consent_given);
        setLoadError(null);
      })
      .catch(setLoadError);
  }, [cloneId]);

  useEffect(load, [load]);

  async function run(label: string, work: () => Promise<unknown>, success: string) {
    setBusy(label);
    setNotice(null);
    try {
      await work();
      const fresh = await getAvatarSettings(cloneId);
      setSettings(fresh);
      setConsentChecked(fresh.avatar_consent_given);
      setNotice({ kind: "success", text: success });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong." });
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => () => uploadAbort.current?.abort(), []);

  async function upload(file: File) {
    const problem = validateAvatarImage(file);
    if (problem) {
      setNotice({ kind: "error", text: problem });
      return;
    }
    const controller = new AbortController();
    uploadAbort.current = controller;
    setFailedFile(null);
    setUploadProgress(0);
    await run(
      "upload",
      async () => {
        try {
          await uploadAvatarWithProgress(cloneId, file, {
            signal: controller.signal,
            onProgress: (fraction) => setUploadProgress(fraction),
            onUploaded: () => setUploadProgress("processing"),
          });
        } catch (err) {
          if (!isAbortError(err)) setFailedFile(file);
          throw isAbortError(err) ? new Error("Upload cancelled.") : err;
        } finally {
          uploadAbort.current = null;
          setUploadProgress(null);
        }
      },
      "Avatar uploaded.",
    );
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void upload(file);
  }

  function setMouth(event: React.MouseEvent<HTMLImageElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const mouth_x = Math.min(0.95, Math.max(0.05, (event.clientX - box.left) / box.width));
    const mouth_y = Math.min(0.95, Math.max(0.05, (event.clientY - box.top) / box.height));
    void run("mouth", () => updateAvatarSettings(cloneId, { mouth_x, mouth_y }), "Mouth position saved.");
  }

  async function startTest() {
    setBusy("test");
    setNotice(null);
    setTestJob(null);
    try {
      setTestJob((await createTestVideo(cloneId, testText.trim() || "Hello, I am an AI Clone.")).job_id);
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "The test video couldn't start." });
    } finally {
      setBusy(null);
    }
  }

  if (loadError) return <ApiErrorState error={loadError} thing="clone" onRetry={load} />;
  if (!clone || !settings) return <StatusMessage title="Loading avatar settings…" />;

  const consented = settings.avatar_consent_given;
  const active = settings.active_avatar;
  const canEnable = consented && active?.status === "ready";

  return (
    <div className="mx-auto max-w-3xl px-4 pb-8 pt-6 sm:px-6 sm:pb-12 sm:pt-12">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Link href={`/clone/${clone.id}/details`} className="inline-flex min-h-11 items-center text-muted hover:text-white md:min-h-0">
          ← Back to {clone.name}
        </Link>
        <Link href={`/clone/${clone.id}`} className="inline-flex min-h-11 items-center text-accent-soft hover:underline md:min-h-0">
          Open chat
        </Link>
      </div>
      <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Avatar</h1>
      <p className="mt-2 text-muted">Give {clone.name} a face that speaks its answers.</p>
      <p className="mt-3 rounded-xl border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-accent-soft">
        AI-generated avatar. Videos are made by AI from a still image and the AI voice. They are not real footage of
        the person.
      </p>

      {settings.lipsync_provider === "fal" && (
        <p className="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-sm text-amber-200">
          Realistic videos are made by a cloud service (fal.ai): your avatar photo and the spoken answer are sent to it
          to create each video. Only use a photo of yourself, or one you have permission to use.
        </p>
      )}
      {!settings.lipsync_provider && (
        <div className="mt-4">
          <FormAlert>Avatar videos are turned off on this server (LIPSYNC_PROVIDER / AVATAR_ENABLED).</FormAlert>
        </div>
      )}
      {!settings.voice_enabled && (
        <p className="mt-4 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-sm text-amber-200">
          The avatar speaks with the clone&apos;s voice.{" "}
          <Link href={`/clone/${clone.id}/voice`} className="underline">
            Turn on voice
          </Link>{" "}
          to make videos.
        </p>
      )}
      {notice && (
        <div className="mt-4">
          <FormAlert kind={notice.kind}>{notice.text}</FormAlert>
        </div>
      )}

      <section className="mt-8 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="avatar-consent">
        <h2 id="avatar-consent" className="text-lg font-semibold">Consent</h2>
        {consented ? (
          <>
            <p className="mt-2 text-sm text-emerald-200">
              Consent given{settings.avatar_consent_at ? ` on ${new Date(settings.avatar_consent_at).toLocaleString()}` : ""}.
            </p>
            <button
              type="button"
              onClick={() => run("withdraw", () => updateAvatarSettings(cloneId, { avatar_consent_given: false }), "Consent withdrawn. The avatar is off.")}
              disabled={busy !== null}
              className="mt-4 rounded-xl border border-rose-500/40 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
            >
              Withdraw consent
            </button>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-muted">You can add an avatar only after confirming this.</p>
            <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm">
              <input
                id="avatar-consent-check"
                type="checkbox"
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                className="mt-0.5 accent-accent"
              />
              I confirm that I have permission to use this person&apos;s image for this AI Clone.
            </label>
            <button
              type="button"
              onClick={() => run("consent", () => updateAvatarSettings(cloneId, { avatar_consent_given: true }), "Consent saved.")}
              disabled={!consentChecked || busy !== null}
              className="mt-4 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save Consent
            </button>
          </>
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="avatar-image">
        <h2 id="avatar-image" className="text-lg font-semibold">Avatar</h2>
        <div className="mt-4 flex flex-col gap-5 sm:flex-row">
          <div className="relative w-full max-w-[16rem] shrink-0">
            {active ? (
              <>
                <ProtectedImage
                  src={active.image_url}
                  alt="Current avatar"
                  onClick={setMouth}
                  className="aspect-square w-full cursor-crosshair rounded-2xl bg-surface object-cover"
                />
                <span
                  className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-rose-500/80"
                  style={{ left: `${active.mouth_x * 100}%`, top: `${active.mouth_y * 100}%` }}
                  aria-hidden
                />
              </>
            ) : (
              <div className="flex aspect-square w-full items-center justify-center rounded-2xl border border-dashed border-border text-sm text-muted">
                No avatar yet
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-3 text-sm">
            {active && (
              <>
                <p className="flex flex-wrap items-center gap-2">
                  <span className="text-muted">Status:</span>
                  <span className={cn("rounded-full border px-2.5 py-0.5 text-xs", STATUS_STYLES[active.status])}>
                    {STATUS_TEXT[active.status]}
                  </span>
                  <span className="text-xs text-muted">({active.avatar_type})</span>
                </p>
                <p className="text-xs text-muted">
                  {active.face_detected
                    ? "Tap the picture to adjust where the mouth is (red dot)."
                    : "No face was found. Tap the picture on the mouth so the lips move in the right place."}
                </p>
              </>
            )}
            {/* Gallery picker (no camera permission needed) and a separate, optional "Take photo". */}
            <input ref={fileInput} type="file" accept="image/*" onChange={onFile} className="hidden" id="avatar-file" />
            <input ref={cameraInput} type="file" accept="image/*" capture="user" onChange={onFile} className="hidden" id="avatar-camera" />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                disabled={!consented || busy !== null}
                className="min-h-11 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-ink hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span aria-hidden>🖼 </span>
                {busy === "upload" ? "Uploading…" : active ? "Choose new photo" : "Choose photo"}
              </button>
              <button
                type="button"
                onClick={() => cameraInput.current?.click()}
                disabled={!consented || busy !== null}
                className="hidden min-h-11 items-center rounded-xl border border-accent/50 px-4 py-2 text-sm text-accent-soft hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:inline-flex"
              >
                <span aria-hidden>📷&nbsp;</span>Take photo
              </button>
              {active && (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  disabled={busy !== null}
                  className="min-h-11 rounded-xl border border-rose-500/40 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
                >
                  Delete Avatar
                </button>
              )}
            </div>
            {uploadProgress !== null && (
              <div aria-live="polite">
                <div
                  className="h-1.5 overflow-hidden rounded-full bg-border"
                  role="progressbar"
                  aria-label="Avatar upload"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={uploadProgress === "processing" ? 100 : Math.round(uploadProgress * 100)}
                >
                  <div
                    className={cn("h-full bg-accent transition-all", uploadProgress === "processing" && "animate-pulse")}
                    style={{ width: `${uploadProgress === "processing" ? 100 : Math.round(uploadProgress * 100)}%` }}
                  />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-muted">
                  <span>
                    {uploadProgress === "processing"
                      ? "Processing image (finding the face)…"
                      : `Uploading… ${Math.round(uploadProgress * 100)}%`}
                  </span>
                  {uploadProgress !== "processing" && (
                    <button
                      type="button"
                      onClick={() => uploadAbort.current?.abort()}
                      className="min-h-11 px-2 text-muted underline hover:text-white"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            )}
            {failedFile && busy === null && (
              <button
                type="button"
                onClick={() => void upload(failedFile)}
                className="min-h-11 rounded-xl border border-amber-400/40 px-4 py-2 text-sm text-amber-300 hover:bg-amber-400/10"
              >
                ↻ Retry upload
              </button>
            )}
            <p className="text-xs text-muted">
              JPG, PNG or WebP, up to {AVATAR_MAX_MB} MB. A clear, front-facing photo of one person works best. The camera
              only opens if you tap &quot;Take photo&quot;.
            </p>
          </div>
        </div>

        <div className="mt-6 border-t border-border pt-5">
          <h3 className="text-sm font-semibold">Or use an illustrated avatar</h3>
          <p className="mt-1 text-xs text-muted">Drawn by the app, not a real person&apos;s face.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {settings.presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => run("preset", () => generateAvatar(cloneId, { preset: preset.id }), `Preset "${preset.name}" is now the avatar.`)}
                disabled={!consented || busy !== null}
                className="min-h-11 rounded-full border border-border px-3 py-1.5 text-xs hover:border-accent disabled:opacity-50 md:min-h-0"
              >
                {preset.name}
              </button>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {(["skin", "hair", "background", "shirt"] as const).map((key) => (
              <Field key={key} label={key[0].toUpperCase() + key.slice(1)} htmlFor={`style-${key}`}>
                <input
                  id={`style-${key}`}
                  type="color"
                  value={style[key]}
                  onChange={(e) => setStyle((prev) => ({ ...prev, [key]: e.target.value }))}
                  className="h-10 w-full cursor-pointer rounded-lg border border-border bg-surface"
                />
              </Field>
            ))}
            <Field label="Hair style" htmlFor="style-hair-style">
              <select
                id="style-hair-style"
                value={style.hair_style}
                onChange={(e) => setStyle((prev) => ({ ...prev, hair_style: e.target.value as AvatarStyle["hair_style"] }))}
                className={`${inputClass} max-sm:text-base`}
              >
                <option value="short">Short</option>
                <option value="long">Long</option>
                <option value="bun">Bun</option>
                <option value="none">None</option>
              </select>
            </Field>
          </div>
          <button
            type="button"
            onClick={() => run("generate", () => generateAvatar(cloneId, { style }), "Illustrated avatar created.")}
            disabled={!consented || busy !== null}
            className="mt-3 min-h-11 rounded-xl border border-accent/50 px-4 py-2 text-sm text-accent-soft hover:bg-accent/10 disabled:opacity-50"
          >
            {busy === "generate" ? "Creating…" : "Generate Avatar"}
          </button>
        </div>

        {settings.avatars.length > 1 && (
          <div className="mt-6 border-t border-border pt-5">
            <h3 className="text-sm font-semibold">Your avatars</h3>
            <ul className="mt-3 flex flex-wrap gap-3">
              {settings.avatars.map((avatar) => (
                <li key={avatar.id} className="w-20 text-center">
                  <ProtectedImage src={avatar.image_url} alt={`${avatar.avatar_type} avatar`} className={cn("aspect-square w-20 rounded-xl object-cover", avatar.is_active && "ring-2 ring-accent")} />
                  {!avatar.is_active && (
                    <button
                      type="button"
                      onClick={() => run("choose", () => updateAvatarSettings(cloneId, { active_avatar_id: avatar.id }), "Avatar selected.")}
                      disabled={busy !== null}
                      className="mt-1 min-h-11 px-2 text-xs text-accent-soft hover:underline md:min-h-0"
                    >
                      Use
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="avatar-enable">
        <h2 id="avatar-enable" className="text-lg font-semibold">Avatar replies</h2>
        <label className="mt-4 flex min-h-11 cursor-pointer items-center gap-3 text-sm">
          <input
            id="avatar-enabled"
            type="checkbox"
            checked={settings.avatar_enabled}
            disabled={!canEnable || busy !== null}
            onChange={(e) => run("enable", () => updateAvatarSettings(cloneId, { avatar_enabled: e.target.checked }), e.target.checked ? "Avatar turned on." : "Avatar turned off.")}
            className="accent-accent"
          />
          <span>
            <span className="font-medium">Avatar Enabled</span>
            <span className="block text-xs text-muted">
              {canEnable ? "Adds the Avatar response mode to your chat." : "Give consent and add an avatar first."}
            </span>
          </span>
        </label>
      </section>

      <section className="mt-6 rounded-2xl border border-border bg-surface-raised p-5 sm:p-7" aria-labelledby="avatar-test">
        <h2 id="avatar-test" className="text-lg font-semibold">Preview</h2>
        <p className="mt-1 text-sm text-muted">Up to {settings.max_video_seconds} seconds of speech.</p>
        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label htmlFor="avatar-test-text" className="sr-only">Text to say</label>
          <input id="avatar-test-text" value={testText} maxLength={500} onChange={(e) => setTestText(e.target.value)} className={`${inputClass} max-sm:text-base`} />
          <button
            type="button"
            onClick={startTest}
            disabled={!settings.avatar_enabled || !settings.voice_enabled || busy !== null}
            className="min-h-11 shrink-0 rounded-xl border border-accent/50 px-5 py-2.5 text-sm text-accent-soft hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "test" ? "Starting…" : "Generate Test Avatar"}
          </button>
        </div>
        {testJob && (
          <div className="mt-4">
            <AvatarVideo
              key={testJob}
              cloneId={clone.id}
              jobId={testJob}
              posterPath={active?.image_url}
              onRetry={busy === null ? () => void startTest() : undefined}
            />
          </div>
        )}
      </section>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this avatar?"
        message="The image is deleted. Videos already made keep working until they expire."
        confirmLabel="Delete Avatar"
        busyLabel="Deleting…"
        busy={busy === "delete"}
        onConfirm={() => {
          if (!active) return;
          void run("delete", () => deleteAvatar(cloneId, active.id), "Avatar deleted.").then(() => setConfirmDelete(false));
        }}
        onCancel={() => setConfirmDelete(false)}
      />

      <LiveAvatarSetup
        key={`${active?.id ?? "none"}-${consented}`}
        cloneId={cloneId}
        hasPhoto={active?.status === "ready"}
        consented={consented}
      />
    </div>
  );
}
