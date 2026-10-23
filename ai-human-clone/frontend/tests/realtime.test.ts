import assert from "node:assert/strict";
import test from "node:test";

import { type AudioPlayer, AudioQueue } from "../lib/realtime/audioQueue.ts";
import { closeCodeError, errorFromBody, isRetryable, micErrorCode, realtimeErrorMessage } from "../lib/realtime/errors.ts";
import { FrameAssembler, SentenceBuffer, buildWsUrl, clientMessage, parseServerMessage } from "../lib/realtime/protocol.ts";
import {
  INITIAL_REALTIME,
  type RealtimeEvent,
  type RealtimeState,
  canStart,
  currentTurn,
  elapsedSeconds,
  formatClock,
  realtimeReducer,
} from "../lib/realtime/session.ts";
import { DEFAULT_VAD, INITIAL_VAD, type VadEvent, rms, vadStep } from "../lib/realtime/vad.ts";

// --- VAD ---

function runVad(levels: number[], aiSpeaking = false, dt = 50): VadEvent[] {
  let state = INITIAL_VAD;
  const events: VadEvent[] = [];
  for (const level of levels) {
    const step = vadStep(state, level, dt, aiSpeaking);
    state = step.state;
    if (step.event) events.push(step.event);
  }
  return events;
}

const loud = (n: number) => Array<number>(n).fill(0.1);
const quiet = (n: number) => Array<number>(n).fill(0.001);

test("vad: an utterance starts after a short burst and ends after ~800 ms of silence", () => {
  assert.deepEqual(runVad([...quiet(5), ...loud(20), ...quiet(20)]), ["speech_start", "speech_end"]);
});

test("vad: a click shorter than startMs is ignored", () => {
  assert.deepEqual(runVad([...loud(1), ...quiet(30)]), []);
});

test("vad: speech shorter than minSpeechMs is too_short (dropped)", () => {
  // 150 ms above threshold starts speech, but 150 ms < minSpeechMs (300 ms).
  assert.deepEqual(runVad([...loud(3), ...quiet(20)]), ["speech_start", "too_short"]);
});

test("vad: pauses shorter than the end silence don't split an utterance", () => {
  assert.deepEqual(runVad([...loud(10), ...quiet(8), ...loud(10), ...quiet(20)]), ["speech_start", "speech_end"]);
});

test("vad: an utterance is cut at maxUtteranceMs", () => {
  const events: VadEvent[] = [];
  let state = INITIAL_VAD;
  for (let i = 0; i < 200; i += 1) {
    const step = vadStep(state, 0.1, 50, false, { ...DEFAULT_VAD, maxUtteranceMs: 2000 });
    state = step.state;
    if (step.event) events.push(step.event);
  }
  assert.deepEqual(events.slice(0, 2), ["speech_start", "max_length"]);
});

test("vad: while the clone speaks, echo-level sound doesn't start speech but a real barge-in does", () => {
  assert.deepEqual(runVad(Array<number>(20).fill(0.04), true), []); // above start, below barge-in threshold
  assert.deepEqual(runVad(Array<number>(20).fill(0.04), false), ["speech_start"]);
  assert.deepEqual(runVad(Array<number>(20).fill(0.1), true), ["speech_start"]);
});

test("vad: rms", () => {
  assert.equal(rms([]), 0);
  assert.ok(Math.abs(rms([0.5, -0.5, 0.5, -0.5]) - 0.5) < 1e-9);
});

// --- Protocol ---

test("protocol: valid messages are parsed, unknown and malformed ones ignored", () => {
  assert.deepEqual(parseServerMessage('{"type":"state","state":"thinking"}'), { type: "state", state: "thinking" });
  assert.deepEqual(parseServerMessage('{"type":"answer","turn":2,"text":"Hi","message_id":"m"}'), {
    type: "answer",
    turn: 2,
    text: "Hi",
    message_id: "m",
  });
  assert.equal(parseServerMessage('{"type":"state","state":"dancing"}'), null);
  assert.equal(parseServerMessage('{"type":"something_new"}'), null);
  assert.equal(parseServerMessage("not json"), null);
  assert.equal(parseServerMessage("[1,2]"), null);
  assert.equal(parseServerMessage('{"type":"answer_delta","turn":"1","text":"x"}'), null);
});

test("protocol: errors and ends are normalised", () => {
  assert.deepEqual(parseServerMessage('{"type":"error","code":"provider_unavailable","message":"busy"}'), {
    type: "error",
    code: "provider_unavailable",
    message: "busy",
    fatal: false,
  });
  assert.deepEqual(parseServerMessage('{"type":"ended","reason":"weird"}'), { type: "ended", reason: "error" });
  assert.deepEqual(parseServerMessage('{"type":"ended","reason":"max_duration"}'), { type: "ended", reason: "max_duration" });
});

test("protocol: an audio header is paired with the next binary frame only", () => {
  const assembler = new FrameAssembler();
  const bytes = new Uint8Array([1, 2, 3]).buffer;
  assert.equal(assembler.feed(bytes), null, "binary without a header is ignored");
  assert.equal(assembler.feed('{"type":"audio","turn":1,"seq":0,"mime":"audio/mpeg"}'), null);
  assert.deepEqual(assembler.feed(bytes), { kind: "audio", turn: 1, seq: 0, mime: "audio/mpeg", data: bytes });
  assert.equal(assembler.feed(bytes), null, "the header is used once");
  assert.deepEqual(assembler.feed('{"type":"pong"}'), { kind: "message", message: { type: "pong" } });
});

test("protocol: client messages and the WebSocket URL", () => {
  assert.equal(clientMessage({ type: "interrupt" }), '{"type":"interrupt"}');
  assert.equal(
    buildWsUrl("http://localhost:8000", "/api/realtime/sessions/abc/ws", "rt_x y"),
    "ws://localhost:8000/api/realtime/sessions/abc/ws?ticket=rt_x+y",
  );
  assert.equal(buildWsUrl("https://api.example.com", "api/realtime/sessions/a/ws", "t"), "wss://api.example.com/api/realtime/sessions/a/ws?ticket=t");
});

test("protocol: streamed text becomes whole sentences for the browser voice", () => {
  const buffer = new SentenceBuffer();
  assert.deepEqual(buffer.push("Hello there"), []);
  assert.deepEqual(buffer.push("! It costs 3.5 rupees. "), ["Hello there!", "It costs 3.5 rupees."]);
  assert.deepEqual(buffer.push("آپ کیسے ہیں؟ ٹھیک"), ["آپ کیسے ہیں؟"]);
  assert.equal(buffer.flush(), "ٹھیک");
  assert.equal(buffer.flush(), null);
});

// --- Audio queue ---

class FakePlayer implements AudioPlayer {
  played: number[] = [];
  stopped = 0;
  private finish: (() => void) | null = null;

  play(data: ArrayBuffer): Promise<void> {
    this.played.push(new Uint8Array(data)[0]);
    return new Promise((resolve) => {
      this.finish = resolve;
    });
  }

  stop(): void {
    this.stopped += 1;
    this.end();
  }

  end(): void {
    const finish = this.finish;
    this.finish = null;
    finish?.();
  }
}

const clip = (id: number) => new Uint8Array([id]).buffer;
const tickAsync = () => new Promise((resolve) => setTimeout(resolve, 0));

test("audio queue: plays in turn/seq order, once each", async () => {
  const player = new FakePlayer();
  const changes: boolean[] = [];
  const queue = new AudioQueue(player, (playing) => changes.push(playing));
  queue.enqueue(1, 0, clip(10));
  queue.enqueue(1, 2, clip(12));
  queue.enqueue(1, 1, clip(11));
  assert.equal(queue.enqueue(1, 1, clip(99)), false, "duplicate ignored");
  for (let i = 0; i < 3; i += 1) {
    await tickAsync();
    player.end();
  }
  await tickAsync();
  assert.deepEqual(player.played, [10, 11, 12]);
  assert.equal(changes[0], true);
  assert.equal(changes.at(-1), false);
});

test("audio queue: interrupting a turn stops it and drops its later clips", async () => {
  const player = new FakePlayer();
  const queue = new AudioQueue(player);
  queue.enqueue(1, 0, clip(10));
  queue.enqueue(1, 1, clip(11));
  await tickAsync();
  queue.interrupt(1);
  await tickAsync();
  assert.equal(player.stopped, 1);
  assert.equal(queue.enqueue(1, 2, clip(12)), false, "late audio of an interrupted turn is dropped");
  queue.enqueue(2, 0, clip(20));
  await tickAsync();
  assert.deepEqual(player.played, [10, 20]);
});

test("audio queue: stop clears everything; close plays nothing more", async () => {
  const player = new FakePlayer();
  const queue = new AudioQueue(player);
  queue.enqueue(3, 0, clip(30));
  queue.enqueue(3, 1, clip(31));
  await tickAsync();
  queue.stop();
  await tickAsync();
  assert.deepEqual(player.played, [30]);
  queue.close();
  assert.equal(queue.enqueue(4, 0, clip(40)), false);
});

// --- Errors ---

test("errors: every contract code and local code has a friendly message", () => {
  for (const code of [
    "realtime_disabled",
    "provider_not_configured",
    "consent_missing",
    "realtime_off",
    "forbidden",
    "rate_limited",
    "too_many_sessions",
    "quota_exceeded",
    "session_not_found",
    "session_expired",
    "provider_unavailable",
    "signaling_failed",
    "mic_denied",
    "mic_missing",
    "mic_busy",
    "unsupported",
    "connection_lost",
    "network",
  ]) {
    assert.ok(!realtimeErrorMessage(code).includes("Something went wrong"), code);
  }
  assert.match(realtimeErrorMessage("nope"), /Something went wrong/);
  assert.equal(realtimeErrorMessage(null, "fallback"), "fallback");
  assert.equal(isRetryable("provider_unavailable"), true);
  assert.equal(isRetryable("consent_missing"), false);
});

test("errors: codes are read from either body shape, else from the status", () => {
  assert.deepEqual(errorFromBody(409, { code: "consent_missing", detail: "Voice consent is required" }), {
    code: "consent_missing",
    message: "Voice consent is required",
  });
  assert.deepEqual(errorFromBody(402, { detail: { code: "quota_exceeded", message: "Limit reached" } }), {
    code: "quota_exceeded",
    message: "Limit reached",
  });
  assert.equal(errorFromBody(429, null).code, "rate_limited");
  assert.equal(errorFromBody(410, {}).code, "session_expired");
  assert.equal(errorFromBody(403, {}).code, "forbidden");
  assert.equal(errorFromBody(502, "html").code, "provider_unavailable");
});

test("errors: WebSocket close codes and microphone failures", () => {
  assert.equal(closeCodeError(1000), null);
  assert.equal(closeCodeError(4403), "forbidden");
  assert.equal(closeCodeError(1013), "provider_unavailable"); // maintenance
  assert.equal(closeCodeError(4404), "session_not_found");
  assert.equal(closeCodeError(4410), "session_expired");
  assert.equal(closeCodeError(4400), "signaling_failed");
  assert.equal(closeCodeError(1006), "connection_lost");
  assert.equal(micErrorCode({ name: "NotAllowedError" }), "mic_denied");
  assert.equal(micErrorCode({ name: "NotFoundError" }), "mic_missing");
  assert.equal(micErrorCode({ name: "NotReadableError" }), "mic_busy");
});

// --- Session reducer ---

function run(events: RealtimeEvent[], from: RealtimeState = INITIAL_REALTIME): RealtimeState {
  return events.reduce(realtimeReducer, from);
}

const ready: RealtimeEvent = {
  type: "server",
  now: 1000,
  message: { type: "ready", session_id: "s1", conversation_id: "c1", speech_mode: "voice", max_duration_seconds: 600 },
};
const connectedEvents: RealtimeEvent[] = [
  { type: "start" },
  { type: "mic_granted" },
  { type: "session_created", sessionId: "s1", conversationId: "c1", speechMode: "voice", maxDurationSeconds: 600 },
  ready,
];

test("session: start → mic → connecting → connected", () => {
  const state = run(connectedEvents);
  assert.equal(state.phase, "connected");
  assert.equal(state.sessionId, "s1");
  assert.equal(state.connectedAt, 1000);
  assert.equal(elapsedSeconds(state, 66_000), 65);
  assert.equal(formatClock(65), "1:05");
  assert.equal(canStart(state), false);
});

test("session: a denied microphone fails before connecting", () => {
  const state = run([{ type: "start" }, { type: "fail", code: "mic_denied" }]);
  assert.equal(state.phase, "failed");
  assert.equal(state.error?.code, "mic_denied");
  assert.equal(canStart(state), true);
});

test("session: transcript, streamed answer, and interruption", () => {
  const msg = (message: Extract<RealtimeEvent, { type: "server" }>["message"]): RealtimeEvent => ({ type: "server", now: 2000, message });
  let state = run([
    ...connectedEvents,
    msg({ type: "state", state: "thinking" }),
    msg({ type: "transcript", turn: 1, text: "Aap kaise hain?", language: "ur" }),
    msg({ type: "answer_delta", turn: 1, text: "Main theek " }),
    msg({ type: "answer_delta", turn: 1, text: "hoon." }),
  ]);
  assert.equal(state.activity, "thinking");
  assert.deepEqual(
    state.transcript.map((e) => [e.role, e.text, e.streaming]),
    [
      ["you", "Aap kaise hain?", false],
      ["clone", "Main theek hoon.", true],
    ],
  );
  assert.equal(currentTurn(state), 1);
  state = run([{ type: "interrupt", turn: 1 }, msg({ type: "answer_delta", turn: 1, text: " late" })], state);
  assert.equal(state.transcript[1].interrupted, true);
  assert.equal(state.transcript[1].text, "Main theek hoon.", "text of an interrupted turn stops growing");
  assert.equal(state.activity, "listening");
});

test("session: a typed message echoed by the server is shown once", () => {
  const state = run([
    ...connectedEvents,
    { type: "user_text", text: "Hello", turn: 1_000_001 },
    { type: "server", now: 3000, message: { type: "transcript", turn: 2, text: "Hello", language: "en" } },
  ]);
  assert.equal(state.transcript.filter((e) => e.role === "you").length, 1);
});

test("session: non-fatal errors keep the session; fatal ones and lost connections fail it", () => {
  let state = run([...connectedEvents, { type: "server", now: 1, message: { type: "error", code: "provider_unavailable", message: "busy", fatal: false } }]);
  assert.equal(state.phase, "connected");
  assert.equal(state.error?.code, "provider_unavailable");
  state = run([{ type: "dismiss_error" }], state);
  assert.equal(state.error, null);
  state = run([{ type: "closed", errorCode: "connection_lost" }], state);
  assert.equal(state.phase, "failed");
  assert.equal(state.error?.code, "connection_lost");
});

test("session: ending by the user or by the server's time limit", () => {
  let state = run([...connectedEvents, { type: "end_requested" }, { type: "closed", errorCode: null }]);
  assert.equal(state.phase, "ended");
  assert.equal(state.endReason, "client");
  state = run([...connectedEvents, { type: "server", now: 1, message: { type: "ended", reason: "max_duration" } }]);
  assert.equal(state.phase, "ended");
  assert.equal(state.endReason, "max_duration");
  // A new session starts fresh but keeps the chosen speech mode.
  state = run([{ type: "set_speech_mode", mode: "browser" }, { type: "start" }], state);
  assert.equal(state.phase, "requesting_mic");
  assert.equal(state.speechMode, "browser");
  assert.deepEqual(state.transcript, []);
});

test("session: start is ignored while a session is live", () => {
  const state = run([...connectedEvents, { type: "start" }]);
  assert.equal(state.phase, "connected");
});
