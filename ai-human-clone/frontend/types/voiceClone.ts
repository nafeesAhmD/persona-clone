/**
 * Personal voice clone: ElevenLabs Instant Voice Cloning, or the free self-hosted
 * Chatterbox service ("local"). See docs/voice-clone/contract.md and docs/voice-clone/local.md.
 */

export type VoiceCloneProvider = "elevenlabs" | "local" | null;

export type VoiceCloneState = "none" | "processing" | "ready" | "failed";

export interface VoiceCloneStatus {
  /** The server can clone voices (ELEVENLABS_API_KEY or the local voice-clone service). */
  available: boolean;
  status: VoiceCloneState;
  /** Safe, user-facing reason when status is "failed". */
  error: string | null;
  use_cloned_voice: boolean;
  consent_at: string | null;
  /** Provider of the existing cloned voice, else the one new recordings go to. */
  provider: VoiceCloneProvider;
  min_seconds: number;
  max_seconds: number;
  max_files: number;
  model: string;
}
