import { API_URL, ApiError, apiFetch } from "@/lib/api";

/** Live video call with a clone's avatar (Simli). The Simli API key stays on the server. */

export interface LiveAvatarStatus {
  available: boolean;
  face_status: "none" | "processing" | "ready" | "failed";
  face_ready: boolean;
  face_error: string | null;
  max_minutes: number;
}

export interface LiveCallAvailability {
  can_call: boolean;
  reason: string | null;
}

export interface LiveCallStart {
  session_token: string;
  ice_servers: RTCIceServer[];
  max_seconds: number;
  max_idle_seconds: number;
}

const base = (cloneId: string) => `/api/clones/${encodeURIComponent(cloneId)}`;

export const liveApi = {
  status: (cloneId: string) => apiFetch<LiveAvatarStatus>(`${base(cloneId)}/live-avatar`, { cache: "no-store" }),
  createFace: (cloneId: string) => apiFetch<LiveAvatarStatus>(`${base(cloneId)}/live-avatar/face`, { method: "POST" }),
  setFaceId: (cloneId: string, faceId: string) =>
    apiFetch<LiveAvatarStatus>(`${base(cloneId)}/live-avatar/face-id`, { method: "PUT", body: JSON.stringify({ face_id: faceId }) }),
  availability: (cloneId: string) => apiFetch<LiveCallAvailability>(`${base(cloneId)}/live-call`, { cache: "no-store" }),
  start: (cloneId: string) => apiFetch<LiveCallStart>(`${base(cloneId)}/live-call`, { method: "POST" }),
  end: (cloneId: string, seconds: number) =>
    apiFetch<void>(`${base(cloneId)}/live-call/end`, { method: "POST", body: JSON.stringify({ seconds }), keepalive: true }),
};

const SIMLI_RATE = 16_000;

/**
 * The answer's speech (MP3 from our API) as raw PCM16 mono at 16 kHz, which is
 * what the live face lip-syncs to. Decoding and resampling happen in the browser.
 */
export async function speechAsPcm16(audioUrl: string): Promise<Uint8Array> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${audioUrl}`, { credentials: "include" });
  } catch {
    throw new ApiError("Could not reach the API server");
  }
  if (!response.ok) throw new ApiError("The voice answer isn't available.", response.status);
  const encoded = await response.arrayBuffer();

  const decoder = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await decoder.decodeAudioData(encoded);
  } finally {
    void decoder.close();
  }
  const frames = Math.ceil(decoded.duration * SIMLI_RATE);
  const offline = new OfflineAudioContext(1, Math.max(frames, 1), SIMLI_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  const samples = rendered.getChannelData(0);
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return new Uint8Array(pcm.buffer);
}
