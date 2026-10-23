import type { ChatMessage, ChatSource } from "@/types/clone";

export type VoiceLanguage = "auto" | "en" | "ur";

export interface VoiceOption {
  id: string;
  name: string;
  description: string;
  /** A personalised voice (needs voice consent). */
  is_custom: boolean;
}

export interface VoiceSettings {
  voice_enabled: boolean;
  voice_provider: string | null;
  voice_id: string | null;
  voice_language: VoiceLanguage;
  voice_consent_given: boolean;
  voice_consent_at: string | null;
  voice_type: "ai_generated" | "custom";
  /** Providers the server has configured right now (null = not available). */
  stt_provider: string | null;
  tts_provider: string | null;
  voices: VoiceOption[];
}

export type VoiceSettingsUpdate = Partial<
  Pick<VoiceSettings, "voice_enabled" | "voice_provider" | "voice_id" | "voice_language" | "voice_consent_given">
>;

export interface Transcription {
  text: string;
  language: string | null;
  duration_seconds: number;
}

export interface VoiceChatResponse {
  conversation_id: string;
  transcript: string;
  answer: string;
  audio_url: string | null;
  tts_error: string | null;
  language: string | null;
  duration_seconds: number;
  message: ChatMessage;
  sources: ChatSource[];
  memories_used: number;
}
