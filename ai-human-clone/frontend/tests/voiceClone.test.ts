import assert from "node:assert/strict";
import test from "node:test";

import {
  type SubmitInput,
  SUBMIT_BLOCK_MESSAGES,
  canAddSample,
  canSubmit,
  cleanDuration,
  cloneStatusLabel,
  durationProgress,
  formatDuration,
  isAcceptedAudioFile,
  isCloningAvailable,
  providerCopy,
  realismChecklist,
  submitBlock,
  totalDuration,
} from "../lib/voiceClone.ts";

const base: SubmitInput = {
  available: true,
  voiceConsent: true,
  cloneConsent: true,
  samples: [{ seconds: 40 }, { seconds: 35 }],
  minSeconds: 30,
  maxSeconds: 300,
  maxFiles: 5,
};

test("total duration sums known lengths and counts unknown ones", () => {
  assert.deepEqual(totalDuration([]), { seconds: 0, unknown: 0 });
  assert.deepEqual(totalDuration([{ seconds: 10.5 }, { seconds: 20 }]), { seconds: 30.5, unknown: 0 });
  assert.deepEqual(totalDuration([{ seconds: 10 }, { seconds: null }, { seconds: Infinity }, { seconds: Number.NaN }]), {
    seconds: 10,
    unknown: 3,
  });
});

test("cleanDuration rejects Infinity, NaN, zero and negatives", () => {
  assert.equal(cleanDuration(Infinity), null);
  assert.equal(cleanDuration(Number.NaN), null);
  assert.equal(cleanDuration(0), null);
  assert.equal(cleanDuration(-3), null);
  assert.equal(cleanDuration(undefined), null);
  assert.equal(cleanDuration(12.3), 12.3);
});

test("formatDuration", () => {
  assert.equal(formatDuration(0), "0:00");
  assert.equal(formatDuration(65), "1:05");
  assert.equal(formatDuration(300), "5:00");
  assert.equal(formatDuration(-4), "0:00");
});

test("can submit with consent and a total between min and max", () => {
  assert.equal(submitBlock(base), null);
  assert.equal(canSubmit(base), true);
});

test("submit rules: availability, consents, busy, samples, files, duration", () => {
  assert.equal(submitBlock({ ...base, available: false }), "unavailable");
  assert.equal(submitBlock({ ...base, voiceConsent: false }), "voice_consent");
  assert.equal(submitBlock({ ...base, busy: true }), "busy");
  assert.equal(submitBlock({ ...base, samples: [] }), "no_samples");
  assert.equal(submitBlock({ ...base, samples: Array.from({ length: 6 }, () => ({ seconds: 10 })) }), "too_many_files");
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 20 }] }), "too_short");
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 200 }, { seconds: 150 }] }), "too_long");
  assert.equal(submitBlock({ ...base, cloneConsent: false }), "clone_consent");
  assert.equal(canSubmit({ ...base, cloneConsent: false }), false);
});

test("exact min and max are allowed", () => {
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 30 }] }), null);
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 300 }] }), null);
});

test("unknown lengths are left to the server, unless the known part is already too long", () => {
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 5 }, { seconds: null }] }), null);
  assert.equal(submitBlock({ ...base, samples: [{ seconds: 301 }, { seconds: null }] }), "too_long");
});

test("canAddSample respects max files", () => {
  assert.equal(canAddSample(0, 5), true);
  assert.equal(canAddSample(4, 5), true);
  assert.equal(canAddSample(5, 5), false);
});

test("duration progress gives text for every level", () => {
  const empty = durationProgress({ seconds: 0, unknown: 0 }, 30, 300);
  assert.equal(empty.level, "empty");
  assert.equal(empty.percent, 0);
  const short = durationProgress({ seconds: 20, unknown: 0 }, 30, 300);
  assert.equal(short.level, "short");
  assert.match(short.label, /0:10 more needed/);
  const ok = durationProgress({ seconds: 90, unknown: 0 }, 30, 300);
  assert.equal(ok.level, "ok");
  assert.equal(ok.percent, 30);
  const long = durationProgress({ seconds: 320, unknown: 0 }, 30, 300);
  assert.equal(long.level, "long");
  assert.equal(long.percent, 100);
  assert.match(long.label, /too long/);
  const unknown = durationProgress({ seconds: 10, unknown: 1 }, 30, 300);
  assert.equal(unknown.level, "ok");
  assert.match(unknown.label, /unknown length/);
});

test("file type acceptance", () => {
  assert.equal(isAcceptedAudioFile({ name: "a.webm", type: "audio/webm;codecs=opus" }), true);
  assert.equal(isAcceptedAudioFile({ name: "a.wav", type: "audio/wav" }), true);
  assert.equal(isAcceptedAudioFile({ name: "a.mp3", type: "audio/mpeg" }), true);
  assert.equal(isAcceptedAudioFile({ name: "a.m4a", type: "audio/x-m4a" }), true);
  assert.equal(isAcceptedAudioFile({ name: "a.ogg", type: "audio/ogg" }), true);
  assert.equal(isAcceptedAudioFile({ name: "voice.m4a", type: "" }), true);
  assert.equal(isAcceptedAudioFile({ name: "voice.mp3", type: "application/octet-stream" }), true);
  assert.equal(isAcceptedAudioFile({ name: "photo.jpg", type: "image/jpeg" }), false);
  assert.equal(isAcceptedAudioFile({ name: "notes.txt", type: "text/plain" }), false);
  assert.equal(isAcceptedAudioFile({ name: "fake.mp3", type: "image/png" }), false);
  assert.equal(isAcceptedAudioFile({ name: "noext", type: "" }), false);
});

test("status labels", () => {
  assert.match(cloneStatusLabel("none"), /Not created/);
  assert.match(cloneStatusLabel("processing"), /Creating/);
  assert.match(cloneStatusLabel("failed"), /Failed/);
  assert.match(cloneStatusLabel("ready", true), /speaks with your cloned voice/);
  assert.match(cloneStatusLabel("ready", false), /off/);
});

test("cloning availability: config switch first, then the status", () => {
  assert.equal(isCloningAvailable(false, true), false);
  assert.equal(isCloningAvailable(true, false), false);
  assert.equal(isCloningAvailable(true, true), true);
  assert.equal(isCloningAvailable(undefined, true), true);
  assert.equal(isCloningAvailable(undefined, false), false);
  assert.equal(isCloningAvailable(true, undefined), true);
  assert.equal(isCloningAvailable(undefined, undefined), false);
});

test("realism checklist states", () => {
  const all = realismChecklist({
    voice: { available: true, status: "ready", use_cloned_voice: true },
    avatar: { lipsync_provider: "fal" },
    live: { available: true, face_ready: true, face_status: "ready" },
  });
  assert.deepEqual(all.map((i) => i.state), ["done", "done", "done"]);
  assert.deepEqual(all.map((i) => i.key), ["voice", "videos", "live"]);
  assert.match(all[0].serverHint, /ELEVENLABS_API_KEY/);
  assert.match(all[1].serverHint, /FAL_API_KEY/);
  assert.match(all[2].serverHint, /SIMLI_API_KEY/);

  const none = realismChecklist({ voice: null, avatar: null, live: null });
  assert.deepEqual(none.map((i) => i.state), ["unknown", "unknown", "unknown"]);

  const mixed = realismChecklist({
    voice: { available: true, status: "ready", use_cloned_voice: false },
    avatar: { lipsync_provider: null },
    live: { available: false, face_ready: false, face_status: "none" },
  });
  assert.deepEqual(mixed.map((i) => i.state), ["partial", "unavailable", "unavailable"]);

  const todo = realismChecklist({
    voice: { available: true, status: "failed", use_cloned_voice: false },
    avatar: { lipsync_provider: "fal" },
    live: { available: true, face_ready: false, face_status: "none" },
  });
  assert.deepEqual(todo.map((i) => i.state), ["todo", "done", "todo"]);
  assert.equal(realismChecklist({ voice: { available: false, status: "none", use_cloned_voice: false }, avatar: null, live: null })[0].state, "unavailable");
});

test("texts follow the voice clone provider", () => {
  const local = providerCopy("local");
  assert.match(local.privacy, /on this server by an open-source model \(Chatterbox, MIT\)/);
  assert.match(local.privacy, /Nothing is sent to an outside company/);
  assert.match(local.privacy, /Hindi accent model/);
  assert.match(local.generating, /1–2 minutes/);  // CPU speech is slow: say so while waiting
  assert.equal(providerCopy("elevenlabs").generating, "Generating…");
  assert.doesNotMatch(Object.values(local).join(" "), /ElevenLabs/);
  const eleven = providerCopy("elevenlabs");
  assert.match(eleven.privacy, /sent to ElevenLabs/);
  assert.match(eleven.deleteConfirm, /ElevenLabs/);
  assert.doesNotMatch(Object.values(providerCopy(null)).join(" "), /ElevenLabs|Chatterbox/);
  assert.equal(
    SUBMIT_BLOCK_MESSAGES.unavailable,
    "Voice cloning isn't set up on this server (ELEVENLABS_API_KEY or the local voice-clone service).",
  );
});
