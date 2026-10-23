"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { liveApi, type LiveAvatarStatus } from "@/lib/liveApi";

const STATUS_TEXT: Record<LiveAvatarStatus["face_status"], string> = {
  none: "Not created yet",
  processing: "Being created… (this can take a few minutes, sometimes longer)",
  ready: "Ready",
  failed: "Couldn't be created",
};

/** Owner setup for the live video call: turn the avatar photo into a live face. */
export function LiveAvatarSetup({ cloneId, hasPhoto, consented }: { cloneId: string; hasPhoto: boolean; consented: boolean }) {
  const [status, setStatus] = useState<LiveAvatarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState(false);
  const [faceId, setFaceId] = useState("");

  const load = useCallback(() => {
    liveApi
      .status(cloneId)
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Couldn't load the live avatar."));
  }, [cloneId]);

  useEffect(load, [load]);

  // While the face is being made, check again every 15 seconds.
  useEffect(() => {
    if (status?.face_status !== "processing") return;
    const timer = window.setInterval(load, 15_000);
    return () => window.clearInterval(timer);
  }, [status?.face_status, load]);

  async function run(action: () => Promise<LiveAvatarStatus>) {
    setBusy(true);
    setError(null);
    try {
      setStatus(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  return (
    <section className="mt-8 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5 sm:p-7" aria-labelledby="live-avatar">
      <h2 id="live-avatar" className="text-lg font-semibold">📹 Live video call</h2>
      <p className="mt-1 text-sm text-muted">
        Talk to your clone face to face, like a video call. The live avatar is your photo brought to life: it blinks and moves
        naturally while it listens, and its lips follow its voice when it answers.
      </p>

      {!status.available ? (
        <p className="mt-4 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-sm text-amber-200">
          Live calls aren&apos;t set up on this server yet: add <code>SIMLI_API_KEY</code> to the .env file (see README).
        </p>
      ) : (
        <>
          <p className="mt-4 text-sm">
            Live face: <strong className={status.face_ready ? "text-emerald-300" : "text-white"}>{STATUS_TEXT[status.face_status]}</strong>
          </p>
          {status.face_error && <p className="mt-1 text-sm text-rose-300">{status.face_error}</p>}
          {error && <p role="alert" className="mt-2 text-sm text-rose-300">{error}</p>}

          <div className="mt-4 flex flex-wrap gap-2">
            {status.face_ready ? (
              <Link href={`/clone/${cloneId}/call`} className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-black hover:bg-emerald-400">
                Start video call
              </Link>
            ) : null}
            <button
              type="button"
              disabled={busy || !hasPhoto || !consented || status.face_status === "processing"}
              onClick={() => run(() => liveApi.createFace(cloneId))}
              className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-raised disabled:opacity-50"
            >
              {busy ? "Sending…" : status.face_ready ? "Re-create from current photo" : "Create live face from my photo"}
            </button>
            <button type="button" onClick={() => setManual((m) => !m)} className="px-2 text-sm text-muted underline">
              I already have a Simli face ID
            </button>
          </div>
          {(!hasPhoto || !consented) && (
            <p className="mt-2 text-xs text-muted">Upload a photo and give avatar consent above first.</p>
          )}
          {manual && (
            <form
              className="mt-3 flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (faceId.trim()) void run(() => liveApi.setFaceId(cloneId, faceId.trim()));
              }}
            >
              <input
                value={faceId}
                onChange={(e) => setFaceId(e.target.value)}
                placeholder="Face ID from app.simli.com"
                maxLength={100}
                aria-label="Simli face ID"
                className="min-w-56 flex-1 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              />
              <button type="submit" disabled={busy} className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-raised">
                Use this face
              </button>
            </form>
          )}
          <p className="mt-4 text-xs text-muted">
            Your avatar photo is sent once to Simli (simli.com) to create the live face, and during calls the clone&apos;s spoken
            answers are streamed to it. Use a clear, front-facing photo with good light. Calls last up to {status.max_minutes} minutes.
            Changing the photo or withdrawing consent removes the live face.
          </p>
        </>
      )}
    </section>
  );
}
