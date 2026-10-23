"use client";

/**
 * Live voice conversation with a clone (Phase 17, docs/phase17/contract.md).
 *
 * The microphone is only opened after start(). The browser cuts the user's speech into
 * utterances with energy-based voice activity detection (lib/realtime/vad.ts) and sends
 * each one as a single binary WebSocket frame; the server answers with streamed text and,
 * in "voice" mode, one audio clip per sentence, played in order by AudioQueue. Talking
 * over the clone (or pressing Interrupt) stops its audio at once and tells the server to
 * cancel the answer. In "browser" mode the streamed sentences are read by the browser's
 * own voice instead (instant, but not the clone's voice).
 *
 * Nothing reconnects by itself: after a failure the user starts a new session.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { beginBusy } from "@/lib/busy";
import { AudioQueue, createElementPlayer } from "@/lib/realtime/audioQueue";
import { closeCodeError, micErrorCode } from "@/lib/realtime/errors";
import { FrameAssembler, SentenceBuffer, clientMessage } from "@/lib/realtime/protocol";
import {
  INITIAL_REALTIME,
  type RealtimeState,
  currentTurn,
  elapsedSeconds,
  realtimeReducer,
} from "@/lib/realtime/session";
import { DEFAULT_VAD, INITIAL_VAD, type VadState, rms, vadStep } from "@/lib/realtime/vad";
import {
  RealtimeApiError,
  type RealtimeTarget,
  createRealtimeSession,
  endRealtimeSession,
  realtimeSocketUrl,
} from "@/lib/realtimeApi";
import type { ClientMessage, RealtimeSpeechMode, ServerMessage } from "@/types/realtime";

const TICK_MS = 50;
const RECORDER_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
const ARABIC_SCRIPT = /[؀-ۿ]/;
const DEVANAGARI = /[ऀ-ॿ]/;

/** Why this browser can't do live voice, or null. */
export function realtimeSupportProblem(): "unsupported" | null {
  if (typeof window === "undefined") return null;
  const ok =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof window.MediaRecorder !== "undefined" &&
    typeof window.WebSocket !== "undefined" &&
    typeof (window.AudioContext ?? (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext) !== "undefined";
  return ok ? null : "unsupported";
}

function recorderType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return RECORDER_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

function speakSentence(text: string, onDone: () => void): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return onDone();
  const utterance = new SpeechSynthesisUtterance(text);
  const lang = ARABIC_SCRIPT.test(text) ? "ur" : DEVANAGARI.test(text) ? "hi" : "en";
  const voices = window.speechSynthesis.getVoices().filter((voice) => voice.lang.toLowerCase().startsWith(lang));
  const voice = voices.find((v) => /natural|online/i.test(v.name)) ?? voices[0];
  if (voice) utterance.voice = voice;
  utterance.lang = voice?.lang ?? (lang === "ur" ? "ur-PK" : lang === "hi" ? "hi-IN" : "en-US");
  utterance.onend = onDone;
  utterance.onerror = onDone;
  window.speechSynthesis.speak(utterance); // queued after any sentence still speaking
}

interface Options {
  /** Speech mode to ask for (the session may override it with the clone's setting). */
  initialSpeechMode?: RealtimeSpeechMode;
  maxUtteranceSeconds?: number;
  maxUtteranceBytes?: number;
}

export interface RealtimeVoice {
  state: RealtimeState;
  elapsed: number;
  /** Microphone level 0..1, for a meter. */
  level: number;
  /** The clone's audio (or browser voice) is playing. */
  speaking: boolean;
  /** The user is talking right now (an utterance is being recorded). */
  userTalking: boolean;
  start: () => void;
  end: () => void;
  interrupt: () => void;
  toggleMute: () => void;
  sendText: (text: string) => void;
  setSpeechMode: (mode: RealtimeSpeechMode) => void;
  dismissError: () => void;
}

export function useRealtimeVoice(target: RealtimeTarget, options: Options = {}): RealtimeVoice {
  const [state, dispatch] = useReducer(realtimeReducer, {
    ...INITIAL_REALTIME,
    speechMode: options.initialSpeechMode ?? "voice",
  });
  const [now, setNow] = useState(() => Date.now());
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [userTalking, setUserTalking] = useState(false);

  // Latest values for the socket/audio callbacks (which outlive a render).
  const stateRef = useRef(state);
  const targetRef = useRef(target);
  useEffect(() => {
    stateRef.current = state;
    targetRef.current = target;
  });

  const ws = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null);
  const vad = useRef<VadState>(INITIAL_VAD);
  const recorder = useRef<MediaRecorder | null>(null);
  const discardRecording = useRef(false);
  const queue = useRef<AudioQueue | null>(null);
  const assembler = useRef(new FrameAssembler());
  const sentences = useRef(new SentenceBuffer());
  const browserSpeaking = useRef(0);
  const queuePlaying = useRef(false);
  const busyDone = useRef<(() => void) | null>(null);
  const sessionId = useRef<string | null>(null);
  const lastServerTurn = useRef(-1);
  const interruptedTurn = useRef(-1);
  const localTurn = useRef(1_000_000); // ids for typed messages shown before the server echoes them
  const live = useRef(false);

  const maxBytes = options.maxUtteranceBytes ?? 2_000_000;
  const maxUtteranceMs = (options.maxUtteranceSeconds ?? 30) * 1000;

  const updateSpeaking = useCallback(() => {
    setSpeaking(queuePlaying.current || browserSpeaking.current > 0);
  }, []);

  const send = useCallback((message: ClientMessage) => {
    const socket = ws.current;
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(clientMessage(message));
  }, []);

  const stopBrowserVoice = useCallback(() => {
    sentences.current.clear();
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    browserSpeaking.current = 0;
    updateSpeaking();
  }, [updateSpeaking]);

  /** Releases the microphone, audio, recorder and socket. Safe to call twice. */
  const teardown = useCallback(() => {
    live.current = false;
    if (ticker.current) clearInterval(ticker.current);
    ticker.current = null;
    const rec = recorder.current;
    recorder.current = null;
    if (rec && rec.state !== "inactive") {
      discardRecording.current = true;
      try {
        rec.stop();
      } catch {
        // Already stopped.
      }
    }
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    analyser.current = null;
    void audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    queue.current?.close();
    queue.current = null;
    queuePlaying.current = false;
    stopBrowserVoice();
    assembler.current.reset();
    const socket = ws.current;
    ws.current = null;
    if (socket && socket.readyState <= WebSocket.OPEN) {
      socket.onclose = null;
      socket.onmessage = null;
      try {
        socket.close(1000);
      } catch {
        // Ignore.
      }
    }
    busyDone.current?.();
    busyDone.current = null;
    vad.current = INITIAL_VAD;
    setUserTalking(false);
    setLevel(0);
  }, [stopBrowserVoice]);

  /** Stops what the clone is saying now (locally and on the server). */
  const interrupt = useCallback(() => {
    if (!live.current) return;
    const turn = Math.max(lastServerTurn.current, currentTurn(stateRef.current));
    interruptedTurn.current = Math.max(interruptedTurn.current, turn);
    queue.current?.interrupt(turn);
    stopBrowserVoice();
    send({ type: "interrupt" });
    dispatch({ type: "interrupt", turn });
  }, [send, stopBrowserVoice]);

  const startRecording = useCallback(() => {
    const source = stream.current;
    if (!source || recorder.current) return;
    const mimeType = recorderType();
    let rec: MediaRecorder;
    try {
      rec = mimeType ? new MediaRecorder(source, { mimeType }) : new MediaRecorder(source);
    } catch {
      return;
    }
    const chunks: Blob[] = [];
    discardRecording.current = false;
    rec.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    rec.onstop = () => {
      const discard = discardRecording.current;
      discardRecording.current = false;
      if (discard || !live.current) return;
      const blob = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
      if (blob.size === 0 || blob.size > maxBytes) return;
      void blob.arrayBuffer().then((buffer) => {
        const socket = ws.current;
        if (live.current && socket && socket.readyState === WebSocket.OPEN) socket.send(buffer);
      });
    };
    recorder.current = rec;
    rec.start();
    setUserTalking(true);
  }, [maxBytes]);

  const stopRecording = useCallback((discard: boolean) => {
    const rec = recorder.current;
    recorder.current = null;
    setUserTalking(false);
    if (!rec || rec.state === "inactive") return;
    discardRecording.current = discard;
    rec.stop();
  }, []);

  const onServerMessage = useCallback(
    (message: ServerMessage) => {
      if ("turn" in message && typeof message.turn === "number") {
        lastServerTurn.current = Math.max(lastServerTurn.current, message.turn);
      }
      const browserMode = stateRef.current.speechMode === "browser";
      switch (message.type) {
        case "answer_delta":
          if (browserMode && message.turn > interruptedTurn.current) {
            for (const sentence of sentences.current.push(message.text)) {
              browserSpeaking.current += 1;
              updateSpeaking();
              speakSentence(sentence, () => {
                browserSpeaking.current = Math.max(0, browserSpeaking.current - 1);
                updateSpeaking();
              });
            }
          }
          break;
        case "answer":
          if (browserMode && message.turn > interruptedTurn.current) {
            const rest = sentences.current.flush();
            if (rest) {
              browserSpeaking.current += 1;
              updateSpeaking();
              speakSentence(rest, () => {
                browserSpeaking.current = Math.max(0, browserSpeaking.current - 1);
                updateSpeaking();
              });
            }
          } else {
            sentences.current.clear();
          }
          break;
        case "interrupted":
          interruptedTurn.current = Math.max(interruptedTurn.current, message.turn);
          queue.current?.interrupt(message.turn);
          stopBrowserVoice();
          break;
        case "ended":
          dispatch({ type: "server", message, now: Date.now() });
          teardown();
          return;
        case "error":
          if (message.fatal) {
            dispatch({ type: "server", message, now: Date.now() });
            teardown();
            return;
          }
          break;
        default:
          break;
      }
      dispatch({ type: "server", message, now: Date.now() });
    },
    [stopBrowserVoice, teardown, updateSpeaking],
  );

  const tick = useCallback(() => {
    const node = analyser.current;
    const current = stateRef.current;
    if (!node || !live.current) return;
    const samples = new Float32Array(node.fftSize);
    node.getFloatTimeDomainData(samples);
    const value = current.muted ? 0 : rms(samples);
    setLevel(value);
    if (current.phase !== "connected") return;
    if (current.muted) {
      if (recorder.current) stopRecording(true);
      vad.current = INITIAL_VAD;
      return;
    }
    const aiSpeaking = queuePlaying.current || browserSpeaking.current > 0;
    const step = vadStep(vad.current, value, TICK_MS, aiSpeaking, { ...DEFAULT_VAD, maxUtteranceMs });
    vad.current = step.state;
    if (step.event === "speech_start") {
      if (aiSpeaking) interrupt(); // barge-in: the user talks over the clone
      startRecording();
    } else if (step.event === "speech_end" || step.event === "max_length") {
      stopRecording(false);
    } else if (step.event === "too_short") {
      stopRecording(true);
    }
  }, [interrupt, maxUtteranceMs, startRecording, stopRecording]);

  const start = useCallback(async () => {
    const phase = stateRef.current.phase;
    if (phase !== "idle" && phase !== "ended" && phase !== "failed") return;
    dispatch({ type: "start" });
    if (realtimeSupportProblem()) {
      dispatch({ type: "fail", code: "unsupported" });
      return;
    }
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (error) {
      dispatch({ type: "fail", code: micErrorCode(error) });
      return;
    }
    stream.current = media;
    dispatch({ type: "mic_granted" });
    busyDone.current = beginBusy(); // a PWA update waits until the session ends
    live.current = true;
    lastServerTurn.current = -1;
    interruptedTurn.current = -1;
    sentences.current.clear();
    assembler.current.reset();

    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      audioCtx.current = ctx;
      const node = ctx.createAnalyser();
      node.fftSize = 1024;
      ctx.createMediaStreamSource(media).connect(node);
      analyser.current = node;
      void ctx.resume().catch(() => undefined);
    } catch {
      teardown();
      dispatch({ type: "fail", code: "unsupported" });
      return;
    }
    queue.current = new AudioQueue(createElementPlayer(), (playing) => {
      queuePlaying.current = playing;
      updateSpeaking();
    });

    let session;
    try {
      session = await createRealtimeSession(targetRef.current);
    } catch (error) {
      teardown();
      const code = error instanceof RealtimeApiError ? error.code : "network";
      dispatch({ type: "fail", code, message: error instanceof RealtimeApiError ? error.message : null });
      return;
    }
    if (!live.current) {
      // Ended while the session was being created.
      void endRealtimeSession(targetRef.current, session.session_id).catch(() => undefined);
      return;
    }
    sessionId.current = session.session_id;
    dispatch({
      type: "session_created",
      sessionId: session.session_id,
      conversationId: session.conversation_id,
      speechMode: stateRef.current.speechMode === "browser" ? "browser" : session.speech_mode,
      maxDurationSeconds: session.max_duration_seconds,
    });

    let socket: WebSocket;
    try {
      socket = new WebSocket(realtimeSocketUrl(session));
    } catch {
      teardown();
      dispatch({ type: "fail", code: "signaling_failed" });
      return;
    }
    socket.binaryType = "arraybuffer";
    ws.current = socket;
    socket.onopen = () => {
      socket.send(clientMessage({ type: "hello" }));
      if (stateRef.current.speechMode === "browser" && session.speech_mode !== "browser") {
        socket.send(clientMessage({ type: "speech_mode", mode: "browser" }));
      }
    };
    socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      const frame = assembler.current.feed(event.data);
      if (!frame) return;
      if (frame.kind === "audio") {
        if (frame.turn > interruptedTurn.current && stateRef.current.speechMode === "voice") {
          queue.current?.enqueue(frame.turn, frame.seq, frame.data, frame.mime);
        }
        return;
      }
      onServerMessage(frame.message);
    };
    socket.onclose = (event) => {
      const wasLive = live.current;
      ws.current = null;
      teardown();
      if (wasLive) dispatch({ type: "closed", errorCode: closeCodeError(event.code) });
    };
    ticker.current = setInterval(tick, TICK_MS);
  }, [onServerMessage, teardown, tick, updateSpeaking]);

  const end = useCallback(() => {
    const id = sessionId.current;
    const phase = stateRef.current.phase;
    if (phase !== "connecting" && phase !== "connected") return;
    dispatch({ type: "end_requested" });
    send({ type: "end" });
    teardown();
    dispatch({ type: "closed", errorCode: null });
    if (id) void endRealtimeSession(targetRef.current, id).catch(() => undefined);
    sessionId.current = null;
  }, [send, teardown]);

  const sendText = useCallback(
    (text: string) => {
      const value = text.trim();
      if (!value || stateRef.current.phase !== "connected") return;
      if (queuePlaying.current || browserSpeaking.current > 0) interrupt();
      send({ type: "text", text: value });
      localTurn.current += 1;
      dispatch({ type: "user_text", text: value, turn: localTurn.current });
    },
    [interrupt, send],
  );

  const toggleMute = useCallback(() => {
    const muted = !stateRef.current.muted;
    stream.current?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
    if (muted && recorder.current) stopRecording(true);
    dispatch({ type: "toggle_mute" });
  }, [stopRecording]);

  const setSpeechMode = useCallback(
    (mode: RealtimeSpeechMode) => {
      if (mode === "browser") queue.current?.stop();
      else stopBrowserVoice();
      send({ type: "speech_mode", mode });
      dispatch({ type: "set_speech_mode", mode });
    },
    [send, stopBrowserVoice],
  );

  const dismissError = useCallback(() => dispatch({ type: "dismiss_error" }), []);

  // Session clock, and the client-side guard for the maximum duration.
  useEffect(() => {
    if (state.phase !== "connected") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state.phase]);

  const elapsed = elapsedSeconds(state, now);
  useEffect(() => {
    if (state.phase === "connected" && elapsed >= state.maxDurationSeconds + 5) end(); // the server should have ended it
  }, [elapsed, end, state.maxDurationSeconds, state.phase]);

  // Tab closed / page left: end the session on the server and release the microphone.
  useEffect(() => {
    const leave = () => {
      const id = sessionId.current;
      if (!live.current && !id) return;
      send({ type: "end" });
      if (id) void endRealtimeSession(targetRef.current, id, true).catch(() => undefined);
      sessionId.current = null;
      teardown();
    };
    window.addEventListener("pagehide", leave);
    return () => {
      window.removeEventListener("pagehide", leave);
      leave(); // unmount (e.g. navigating away inside the app)
    };
  }, [send, teardown]);

  return {
    state,
    elapsed,
    level,
    speaking,
    userTalking,
    start: () => void start(),
    end,
    interrupt,
    toggleMute,
    sendText,
    setSpeechMode,
    dismissError,
  };
}
