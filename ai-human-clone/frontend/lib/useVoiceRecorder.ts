"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { audioExtension } from "@/lib/api";
import { postFormWithProgress, type UploadOptions } from "@/lib/uploadWithProgress";
import { type VoiceErrorCode, checkVoiceSupport, mediaErrorCode, voiceErrorMessage } from "@/lib/voiceStates";
import type { Transcription } from "@/types/voice";
import { beginBusy } from "@/lib/busy";

/** Same limit as MAX_AUDIO_DURATION_SECONDS on the server; recording stops by itself here. */
export const MAX_RECORDING_SECONDS = 60;

// In order of preference; the server accepts all of them. Safari (iOS) records audio/mp4.
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export type RecorderState = "idle" | "requesting" | "recording";

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/** Why recording can't work in this browser, or null when it can. */
export function voiceSupportProblem(): VoiceErrorCode | null {
  if (typeof window === "undefined") return "unsupported";
  return checkVoiceSupport({
    secureContext: window.isSecureContext !== false,
    hasGetUserMedia: Boolean(navigator.mediaDevices?.getUserMedia),
    hasMediaRecorder: typeof MediaRecorder !== "undefined",
  });
}

export function isRecordingSupported(): boolean {
  return voiceSupportProblem() === null;
}

/** Speech to text with upload progress (onUploaded fires when transcription starts). Cancellable. */
export function transcribeRecording(cloneId: string, recording: Blob, options: UploadOptions = {}): Promise<Transcription> {
  const form = new FormData();
  form.append("audio", recording, `voice.${audioExtension(recording.type)}`);
  return postFormWithProgress<Transcription>(`/api/clones/${encodeURIComponent(cloneId)}/voice/transcribe`, form, options);
}

/**
 * Records one voice message. Permission is requested only when startRecording()
 * is called (from a button press). stopRecording() resolves with the audio;
 * cancelRecording() throws it away. When the time limit is reached the recording
 * stops and is handed to `onAutoStop`; callers must not upload it without a tap.
 */
export function useVoiceRecorder(maxSeconds: number = MAX_RECORDING_SECONDS) {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [errorCode, setErrorCode] = useState<VoiceErrorCode | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const finish = useRef<((recording: Blob | null) => void) | null>(null);
  const timer = useRef<number | null>(null);

  const busyDone = useRef<(() => void) | null>(null);
  const release = useCallback(() => {
    busyDone.current?.();
    busyDone.current = null;
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    recorder.current = null;
    setState("idle");
  }, []);

  useEffect(() => release, [release]); // stop the microphone when the page closes

  const fail = useCallback((code: VoiceErrorCode) => {
    setErrorCode(code);
    setErrorText(voiceErrorMessage(code));
  }, []);

  /** Show a custom message (e.g. from the server). */
  const setError = useCallback((message: string | null) => {
    setErrorText(message);
    if (!message) setErrorCode(null);
  }, []);

  const stopRecording = useCallback((): Promise<Blob | null> => {
    const active = recorder.current;
    if (!active || active.state === "inactive") return Promise.resolve(null);
    return new Promise((resolve) => {
      finish.current = resolve;
      active.stop();
    });
  }, []);

  /** Resolves with null once recording started, or with why it couldn't start. */
  const startRecording = useCallback(
    async (onAutoStop?: (recording: Blob | null) => void): Promise<VoiceErrorCode | null> => {
      setErrorCode(null);
      setErrorText(null);
      const problem = voiceSupportProblem();
      if (problem) {
        fail(problem);
        return problem;
      }
      setState("requesting");
      try {
        stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = pickMimeType();
        const media = new MediaRecorder(stream.current, mimeType ? { mimeType } : undefined);
        chunks.current = [];
        media.ondataavailable = (event) => {
          if (event.data.size > 0) chunks.current.push(event.data);
        };
        media.onstop = () => {
          const type = media.mimeType || mimeType || "audio/webm";
          const recording = chunks.current.length ? new Blob(chunks.current, { type }) : null;
          const done = finish.current;
          finish.current = null;
          release();
          if (done) done(recording);
          else onAutoStop?.(recording); // stopped by the time limit
        };
        media.onerror = () => {
          fail("recording_failed");
          finish.current = null;
          release();
        };
        recorder.current = media;
        media.start(250);
        setSeconds(0);
        setState("recording");
        busyDone.current = beginBusy(); // an app update waits until the recording ends
        const started = Date.now();
        timer.current = window.setInterval(() => {
          const elapsed = Math.floor((Date.now() - started) / 1000);
          setSeconds(elapsed);
          if (elapsed >= maxSeconds && media.state === "recording") media.stop();
        }, 250);
        return null;
      } catch (err) {
        const code = mediaErrorCode(err instanceof DOMException || err instanceof Error ? err.name : undefined);
        fail(code);
        release();
        return code;
      }
    },
    [release, fail, maxSeconds],
  );

  const cancelRecording = useCallback(() => {
    const active = recorder.current;
    finish.current = () => undefined; // discard the audio
    if (active && active.state !== "inactive") active.stop();
    else {
      finish.current = null;
      release();
    }
  }, [release]);

  return {
    state,
    seconds,
    maxSeconds,
    error: errorText,
    errorCode,
    setError,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
