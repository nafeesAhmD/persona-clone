import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_VOICE_STATE,
  STAGE_INFO,
  type VoiceEvent,
  type VoiceStage,
  type VoiceState,
  canRetryRecording,
  canStartRecording,
  checkVoiceSupport,
  formatSeconds,
  httpErrorCode,
  isCancellable,
  mediaErrorCode,
  voiceErrorMessage,
  voiceReducer,
} from "../lib/voiceStates.ts";

function run(events: VoiceEvent[], from: VoiceState = INITIAL_VOICE_STATE): VoiceState {
  return events.reduce(voiceReducer, from);
}

test("a full spoken turn with a voice reply goes through every stage in order", () => {
  const stages: VoiceStage[] = [];
  let state = INITIAL_VOICE_STATE;
  const events: VoiceEvent[] = [
    { type: "tap_record" },
    { type: "permission_granted" },
    { type: "upload_started" },
    { type: "uploaded" },
    { type: "transcribed" },
    { type: "answer_ready", speak: true },
    { type: "voice_ready" },
  ];
  for (const event of events) {
    state = voiceReducer(state, event);
    stages.push(state.stage);
  }
  assert.deepEqual(stages, ["requesting", "listening", "uploading", "transcribing", "thinking", "generating_voice", "complete"]);
});

test("a text or avatar reply completes without generating voice", () => {
  const state = run([
    { type: "tap_record" },
    { type: "permission_granted" },
    { type: "upload_started" },
    { type: "transcribed" },
    { type: "answer_ready", speak: false },
  ]);
  assert.equal(state.stage, "complete");
});

test("recording never starts without a tap", () => {
  assert.equal(voiceReducer(INITIAL_VOICE_STATE, { type: "permission_granted" }).stage, "idle");
  assert.equal(voiceReducer(INITIAL_VOICE_STATE, { type: "upload_started" }).stage, "idle");
  assert.equal(voiceReducer(INITIAL_VOICE_STATE, { type: "limit_reached" }).stage, "idle");
});

test("the time limit parks the recording until the user sends it (no automatic upload)", () => {
  const parked = run([{ type: "tap_record" }, { type: "permission_granted" }, { type: "limit_reached" }]);
  assert.equal(parked.stage, "recorded");
  assert.ok(isCancellable(parked.stage));
  // Only an explicit send moves it on.
  assert.equal(voiceReducer(parked, { type: "upload_started" }).stage, "uploading");
  assert.equal(voiceReducer(parked, { type: "cancel" }).stage, "idle");
});

test("cancel works before the transcript is in, not afterwards", () => {
  for (const stage of ["requesting", "listening", "recorded", "uploading", "transcribing"] as VoiceStage[]) {
    assert.equal(voiceReducer({ stage, error: null, detail: null }, { type: "cancel" }).stage, "idle", stage);
  }
  for (const stage of ["thinking", "generating_voice"] as VoiceStage[]) {
    assert.equal(voiceReducer({ stage, error: null, detail: null }, { type: "cancel" }).stage, stage, stage);
  }
});

test("failures land in Error with a code, and a new tap starts over", () => {
  const failed = run([{ type: "tap_record" }, { type: "fail", code: "permission_denied" }]);
  assert.deepEqual(failed, { stage: "error", error: "permission_denied", detail: null });
  assert.ok(canStartRecording(failed));
  assert.equal(voiceReducer(failed, { type: "tap_record" }).stage, "requesting");
  assert.equal(voiceReducer(failed, { type: "reset" }).stage, "idle");
});

test("a failed upload can be retried with the same recording (from Error)", () => {
  const failed = run([
    { type: "tap_record" },
    { type: "permission_granted" },
    { type: "upload_started" },
    { type: "fail", code: "upload_failed" },
  ]);
  assert.ok(canRetryRecording(failed.error));
  assert.equal(voiceReducer(failed, { type: "upload_started" }).stage, "uploading");
  assert.equal(canRetryRecording("permission_denied"), false);
  assert.equal(canRetryRecording("empty_recording"), false);
});

test("no second recording while one is in progress", () => {
  const listening = run([{ type: "tap_record" }, { type: "permission_granted" }]);
  assert.equal(canStartRecording(listening), false);
  assert.equal(voiceReducer(listening, { type: "tap_record" }), listening);
});

test("support check: insecure context and missing APIs", () => {
  assert.equal(checkVoiceSupport({ secureContext: true, hasGetUserMedia: true, hasMediaRecorder: true }), null);
  assert.equal(checkVoiceSupport({ secureContext: false, hasGetUserMedia: true, hasMediaRecorder: true }), "insecure_context");
  assert.equal(checkVoiceSupport({ secureContext: true, hasGetUserMedia: false, hasMediaRecorder: true }), "unsupported");
  assert.equal(checkVoiceSupport({ secureContext: true, hasGetUserMedia: true, hasMediaRecorder: false }), "unsupported");
});

test("getUserMedia errors map to permission / missing / busy microphone", () => {
  assert.equal(mediaErrorCode("NotAllowedError"), "permission_denied");
  assert.equal(mediaErrorCode("NotFoundError"), "no_microphone");
  assert.equal(mediaErrorCode("NotReadableError"), "microphone_busy");
  assert.equal(mediaErrorCode("SecurityError"), "insecure_context");
  assert.equal(mediaErrorCode(undefined), "recording_failed");
});

test("API failures: provider busy (429), unavailable (503), offline, upload failure", () => {
  assert.equal(httpErrorCode(429), "provider_busy");
  assert.equal(httpErrorCode(503), "provider_unavailable");
  assert.equal(httpErrorCode(500), "provider_unavailable");
  assert.equal(httpErrorCode(413), "too_large");
  assert.equal(httpErrorCode(403), "not_allowed");
  assert.equal(httpErrorCode(undefined), "upload_failed");
  assert.equal(httpErrorCode(undefined, "offline"), "offline");
  assert.equal(httpErrorCode(undefined, "timeout"), "provider_unavailable");
  assert.equal(httpErrorCode(402, "usage_limit"), "provider_busy");
});

test("every stage has a text label and every error a message", () => {
  for (const [stage, info] of Object.entries(STAGE_INFO)) {
    assert.ok(info.label.length > 0, stage);
    assert.ok(info.icon.length > 0, stage);
  }
  for (const code of ["unsupported", "permission_denied", "microphone_busy", "provider_busy", "provider_unavailable"] as const) {
    assert.ok(voiceErrorMessage(code).length > 10, code);
  }
});

test("formatSeconds", () => {
  assert.equal(formatSeconds(0), "0:00");
  assert.equal(formatSeconds(65), "1:05");
  assert.equal(formatSeconds(-3), "0:00");
});
