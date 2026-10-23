"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getChatProfile, sendCloneMessage, sendVoiceMessage, speakMessage } from "@/lib/api";
import { liveApi, speechAsPcm16 } from "@/lib/liveApi";
import { useVoiceRecorder } from "@/lib/useVoiceRecorder";
import { useViewportFill } from "@/lib/useViewportFill";
import type { CloneChatProfile } from "@/types/clone";
import { beginBusy } from "@/lib/busy";

type CallState = "checking" | "unavailable" | "ready" | "connecting" | "live" | "ended" | "failed";
type Activity = "listening" | "recording" | "thinking" | "speaking";

// The subset of simli-client used here (it is loaded only in the browser).
interface Simli {
  start(): Promise<void>;
  stop(): Promise<void>;
  sendAudioData(data: Uint8Array): void;
  ClearBuffer(): void;
  on(event: string, callback: (...args: unknown[]) => void): void;
}

const CHUNK_BYTES = 6000; // ~0.19 s of PCM16 at 16 kHz

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * A video call with the clone. The avatar is streamed live by Simli: it idles
 * naturally while listening and lip-syncs the clone's own voice when answering.
 * Each turn is the normal voice (or text) chat, so answers, memory and history
 * work exactly as in the chat.
 */
export function LiveCall({ cloneId }: { cloneId: string }) {
  const [clone, setClone] = useState<CloneChatProfile | null>(null);
  const [state, setState] = useState<CallState>("checking");
  const [activity, setActivity] = useState<Activity>("listening");
  const [reason, setReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [you, setYou] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [captions, setCaptions] = useState(true);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [limit, setLimit] = useState(600);
  const [camera, setCamera] = useState(false);
  /** A recording stopped by the time limit, waiting for the user to send it. */
  const [held, setHeld] = useState<Blob | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const selfRef = useRef<HTMLVideoElement>(null);
  const simli = useRef<Simli | null>(null);
  const callBusy = useRef<(() => void) | null>(null); // an app update waits until the call ends
  const selfStream = useRef<MediaStream | null>(null);
  const startedAt = useRef<number | null>(null);
  const conversation = useRef<string | null>(null);
  const busy = useRef(false);
  const recorder = useVoiceRecorder();
  const frameRef = useViewportFill<HTMLDivElement>();

  // Can this user call this clone?
  useEffect(() => {
    let cancelled = false;
    Promise.all([getChatProfile(cloneId), liveApi.availability(cloneId)])
      .then(([profile, availability]) => {
        if (cancelled) return;
        setClone(profile);
        setReason(availability.reason);
        setState(availability.can_call ? "ready" : "unavailable");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setReason(err instanceof Error ? err.message : "This AI Clone isn't available.");
        setState("unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [cloneId]);

  const stopCamera = useCallback(() => {
    selfStream.current?.getTracks().forEach((t) => t.stop());
    selfStream.current = null;
    setCamera(false);
  }, []);

  const hangUp = useCallback(
    async (next: CallState = "ended") => {
      const client = simli.current;
      simli.current = null;
      callBusy.current?.();
      callBusy.current = null;
      recorder.cancelRecording();
      setHeld(null);
      stopCamera();
      if (startedAt.current !== null) {
        const seconds = (Date.now() - startedAt.current) / 1000;
        startedAt.current = null;
        liveApi.end(cloneId, seconds).catch(() => undefined);
      }
      setState(next);
      setActivity("listening");
      if (client) await client.stop().catch(() => undefined);
    },
    [cloneId, recorder, stopCamera],
  );

  // Leaving the page ends the call.
  useEffect(() => () => void hangUp(), []); // eslint-disable-line react-hooks/exhaustive-deps

  // Call timer, and the hard limit.
  useEffect(() => {
    if (state !== "live") return;
    const timer = window.setInterval(() => {
      if (startedAt.current === null) return;
      const seconds = (Date.now() - startedAt.current) / 1000;
      setElapsed(seconds);
      if (seconds >= limit) void hangUp();
    }, 500);
    return () => window.clearInterval(timer);
  }, [state, limit, hangUp]);

  async function startCall() {
    setError(null);
    setState("connecting");
    try {
      const call = await liveApi.start(cloneId);
      // The package's index imports "./Client" but ships "client.js", which breaks on
      // case-sensitive file systems (Linux/Docker), so load the module directly.
      const { SimliClient, LogLevel } = await import("simli-client/dist/client");
      if (!videoRef.current || !audioRef.current) throw new Error("The video player isn't ready.");
      const client = new SimliClient(
        call.session_token,
        videoRef.current,
        audioRef.current,
        call.ice_servers,
        LogLevel.ERROR,
        "p2p",
      ) as unknown as Simli;
      client.on("speaking", () => setActivity("speaking"));
      client.on("silent", () => setActivity((a) => (a === "speaking" ? "listening" : a)));
      client.on("stop", () => {
        if (simli.current === client) void hangUp();
      });
      client.on("error", () => {
        if (simli.current === client) {
          setError("The video connection dropped.");
          void hangUp("failed");
        }
      });
      simli.current = client;
      await client.start();
      startedAt.current = Date.now();
      callBusy.current = beginBusy();
      setLimit(call.max_seconds);
      setElapsed(0);
      setState("live");
      setActivity("listening");
    } catch (err) {
      simli.current = null;
      setError(err instanceof Error ? err.message : typeof err === "string" ? err : "Couldn't start the call.");
      setState("failed");
    }
  }

  /** Stream the answer's speech to the live face; it lip-syncs while the audio plays. */
  async function speak(audioUrl: string | null, text: string) {
    setAnswer(text);
    if (!audioUrl || !simli.current) {
      setError("The voice answer isn't available right now, so it's shown as text.");
      setActivity("listening");
      return;
    }
    const pcm = await speechAsPcm16(audioUrl);
    const client = simli.current;
    if (!client) return;
    for (let i = 0; i < pcm.length; i += CHUNK_BYTES) client.sendAudioData(pcm.subarray(i, i + CHUNK_BYTES));
    setActivity("speaking");
  }

  /** One spoken turn: what you said -> the clone's answer, spoken by the live face. */
  async function askByVoice(recording: Blob | null) {
    if (!recording) {
      setActivity("listening");
      return;
    }
    busy.current = true;
    setActivity("thinking");
    setError(null);
    try {
      const reply = await sendVoiceMessage(cloneId, recording, conversation.current);
      conversation.current = reply.conversation_id;
      setYou(reply.transcript);
      await speak(reply.audio_url, reply.answer);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't get an answer.");
      setActivity("listening");
    } finally {
      busy.current = false;
    }
  }

  async function onMic() {
    if (state !== "live" || busy.current) return;
    if (held) {
      // A recording stopped by the time limit is only sent when you tap.
      const recording = held;
      setHeld(null);
      await askByVoice(recording);
      return;
    }
    if (recorder.state === "recording") {
      await askByVoice(await recorder.stopRecording());
      return;
    }
    simli.current?.ClearBuffer(); // interrupt: the clone stops talking
    setActivity("recording");
    // At the time limit the recorder stops by itself; the audio waits for a tap (never sent automatically).
    const problem = await recorder.startRecording((recording) => {
      setActivity("listening");
      if (recording) setHeld(recording);
    });
    if (problem) setActivity("listening");
  }

  async function sendText(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || state !== "live" || busy.current) return;
    busy.current = true;
    setDraft("");
    setYou(text);
    setActivity("thinking");
    setError(null);
    simli.current?.ClearBuffer();
    try {
      const reply = await sendCloneMessage(cloneId, text, conversation.current);
      conversation.current = reply.conversation_id;
      const { audio_url } = await speakMessage(reply.conversation_id, reply.message.id).catch(() => ({ audio_url: null }));
      await speak(audio_url, reply.message.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't get an answer.");
      setActivity("listening");
    } finally {
      busy.current = false;
    }
  }

  async function toggleCamera() {
    if (camera) return stopCamera();
    try {
      // Only shown to you, like a self-view in a video call; it is never sent anywhere.
      selfStream.current = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 }, audio: false });
      if (selfRef.current) selfRef.current.srcObject = selfStream.current;
      setCamera(true);
    } catch {
      setError("Couldn't open your camera.");
    }
  }

  const live = state === "live";
  const statusText = held
    ? "Time limit reached. Tap the mic to send what you said."
    : activity === "recording"
      ? `Listening to you… ${recorder.seconds}s — tap the mic again to send`
      : activity === "thinking"
        ? `${clone?.name ?? "Clone"} is thinking…`
        : activity === "speaking"
          ? `${clone?.name ?? "Clone"} is speaking`
          : "Tap the mic and talk";

  return (
    <div
      ref={frameRef}
      className="flex h-[calc(100dvh-var(--app-header-h))] flex-col overflow-hidden bg-black pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-white"
    >
      {/* Top bar */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 sm:px-6 sm:py-3 [@media(max-height:500px)]:py-1">
        <div className="min-w-0">
          <p className="truncate font-semibold">{clone?.name ?? "Video call"}</p>
          <p className="truncate text-[11px] text-white/60 sm:text-xs">AI-generated avatar · not a real person on camera</p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs">
          {live && (
            <span className="flex items-center gap-1.5 rounded-full bg-rose-600/90 px-2.5 py-1 font-semibold">
              <span className="h-2 w-2 animate-pulse rounded-full bg-white" aria-hidden /> LIVE {clock(elapsed)}
            </span>
          )}
          <Link
            href={`/clone/${cloneId}`}
            className="inline-flex min-h-11 items-center rounded-full border border-white/20 px-3 text-white/80 hover:text-white"
          >
            <span className="hidden min-[360px]:inline">Back to chat</span>
            <span className="min-[360px]:hidden">Chat</span>
          </Link>
        </div>
      </div>

      {/* Stage */}
      <div className="relative mx-auto flex min-h-0 w-full max-w-5xl flex-1 items-center justify-center px-2 sm:px-6">
        <div className="relative h-full w-full overflow-hidden rounded-3xl bg-neutral-900 shadow-2xl ring-1 ring-white/10 [@media(max-height:500px)]:rounded-xl">
          <video ref={videoRef} autoPlay playsInline className={`h-full w-full object-cover ${live ? "" : "opacity-0"}`} />
          <audio ref={audioRef} autoPlay />

          {!live && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 overflow-y-auto p-4 text-center sm:gap-4 sm:p-6 [@media(max-height:500px)]:gap-2 [@media(max-height:500px)]:p-2">
              {clone?.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={clone.avatar_url} alt="" className="h-20 w-20 rounded-full object-cover ring-4 ring-white/10 sm:h-28 sm:w-28 [@media(max-height:500px)]:h-12 [@media(max-height:500px)]:w-12" />
              ) : (
                <div className="grid h-20 w-20 place-items-center rounded-full bg-white/10 text-3xl font-semibold sm:h-28 sm:w-28 [@media(max-height:500px)]:h-12 [@media(max-height:500px)]:w-12 [@media(max-height:500px)]:text-xl">
                  {clone?.name?.[0] ?? "…"}
                </div>
              )}
              {state === "checking" && <p className="text-white/70">Checking…</p>}
              {state === "connecting" && <p className="animate-pulse text-white/80">Connecting the video call…</p>}
              {state === "unavailable" && (
                <>
                  <p className="max-w-sm text-white/80">{reason ?? "Video calls aren't available."}</p>
                  {clone?.is_owner && (
                    <Link href={`/clone/${cloneId}/avatar`} className="inline-flex min-h-11 items-center rounded-full bg-white/10 px-4 text-sm hover:bg-white/20">
                      Set up the live avatar
                    </Link>
                  )}
                </>
              )}
              {(state === "ready" || state === "ended" || state === "failed") && (
                <>
                  {state === "ended" && <p className="text-white/70">Call ended · {clock(elapsed)}</p>}
                  <button
                    type="button"
                    onClick={startCall}
                    className="min-h-12 rounded-full bg-emerald-500 px-6 py-3 font-semibold text-black shadow-lg hover:bg-emerald-400"
                  >
                    {state === "ready" ? `Start video call with ${clone?.name ?? "the clone"}` : "Call again"}
                  </button>
                  <p className="max-w-sm text-xs text-white/50 [@media(max-height:500px)]:hidden">
                    Calls last up to {Math.round(limit / 60)} minutes. Your microphone is only used while the mic button is on.
                  </p>
                </>
              )}
            </div>
          )}

          {/* Self view (local only) */}
          <video
            ref={selfRef}
            autoPlay
            muted
            playsInline
            className={`absolute right-2 top-2 h-20 w-28 -scale-x-100 rounded-xl object-cover ring-1 ring-white/20 sm:right-3 sm:top-3 sm:h-32 sm:w-44 [@media(max-height:500px)]:h-16 [@media(max-height:500px)]:w-24 ${camera ? "" : "hidden"}`}
          />

          {/* Captions */}
          {live && captions && (you || answer) && (
            <div className="absolute inset-x-0 bottom-0 space-y-1 bg-gradient-to-t from-black/85 to-transparent px-3 pb-3 pt-10 text-sm sm:px-8 sm:pb-4 [@media(max-height:500px)]:pt-6 [@media(max-height:500px)]:text-xs">
              {you && <p className="text-white/60">You: {you}</p>}
              {answer && <p className="line-clamp-4 text-white [@media(max-height:500px)]:line-clamp-2">{answer}</p>}
            </div>
          )}
        </div>
      </div>

      {/* Status and controls */}
      <div className="px-3 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:px-4 [@media(max-height:500px)]:pb-[max(0.25rem,env(safe-area-inset-bottom))] [@media(max-height:500px)]:pt-1">
        {error && (
          <p role="alert" className="mx-auto mb-2 max-w-md rounded-xl bg-rose-500/15 px-3 py-2 text-center text-sm text-rose-200 [@media(max-height:500px)]:py-1 [@media(max-height:500px)]:text-xs">
            {error}
          </p>
        )}
        {live && <p className="mb-2 text-center text-sm text-white/70 [@media(max-height:500px)]:mb-1 [@media(max-height:500px)]:text-xs" aria-live="polite">{statusText}</p>}
        {live && typing && (
          <form onSubmit={sendText} className="mx-auto mb-2 flex max-w-md gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={4000}
              placeholder="Type a message…"
              aria-label="Message"
              enterKeyHint="send"
              className="min-h-11 min-w-0 flex-1 rounded-full bg-white/10 px-4 py-2 text-base outline-none ring-1 ring-white/15 focus:ring-white/40 sm:text-sm"
            />
            <button type="submit" className="min-h-11 shrink-0 rounded-full bg-white/15 px-4 text-sm hover:bg-white/25">
              Send
            </button>
          </form>
        )}
        {live && (
          <div className="flex items-center justify-center gap-2 min-[360px]:gap-3 sm:gap-4">
            <RoundButton label={camera ? "Turn camera off" : "Show my camera"} onClick={toggleCamera} active={camera}>
              🎥
            </RoundButton>
            <RoundButton label="Type instead" onClick={() => setTyping((t) => !t)} active={typing}>
              ⌨️
            </RoundButton>
            <button
              type="button"
              onClick={onMic}
              disabled={activity === "thinking"}
              aria-label={recorder.state === "recording" || held ? "Send what you said" : "Talk"}
              aria-pressed={recorder.state === "recording"}
              className={`grid h-16 w-16 shrink-0 place-items-center rounded-full text-2xl shadow-lg transition disabled:opacity-50 [@media(max-height:500px)]:h-14 [@media(max-height:500px)]:w-14 ${
                recorder.state === "recording" || held ? "animate-pulse bg-emerald-500 text-black" : "bg-white text-black hover:bg-white/90"
              }`}
            >
              🎙️
            </button>
            <RoundButton label={captions ? "Hide captions" : "Show captions"} onClick={() => setCaptions((c) => !c)} active={captions}>
              CC
            </RoundButton>
            <button
              type="button"
              onClick={() => void hangUp()}
              aria-label="End call"
              className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-rose-600 text-xl hover:bg-rose-500"
            >
              ✕
            </button>
          </div>
        )}
        {recorder.error && <p role="alert" className="mt-2 text-center text-sm text-rose-200">{recorder.error}</p>}
      </div>
    </div>
  );
}

function RoundButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`grid h-12 w-12 shrink-0 place-items-center rounded-full text-sm font-semibold ${active ? "bg-white/25" : "bg-white/10 hover:bg-white/20"}`}
    >
      {children}
    </button>
  );
}
