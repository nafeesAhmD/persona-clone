import type { Visibility } from "@/types/clone";

export type ContentVisibility = "private" | "public";

/** What anyone may see about a public or unlisted clone. */
export interface PublicClone {
  id: string;
  name: string;
  slug: string;
  tagline: string | null;
  bio: string | null;
  profession: string | null;
  skills: string[];
  preferred_language: string | null;
  /** An API path (served without login) or an owner-provided URL. */
  avatar_url: string | null;
  visibility: Visibility;
  public_chat_enabled: boolean;
  voice_enabled: boolean;
  avatar_enabled: boolean;
  /** Live voice (Phase 17) is on for visitors. Absent on older servers: treated as off. */
  realtime_voice_available?: boolean;
}

export interface PublicCloneCard {
  name: string;
  slug: string;
  tagline: string | null;
  profession: string | null;
  skills: string[];
  preferred_language: string | null;
  avatar_url: string | null;
}

export interface PublicCloneList {
  items: PublicCloneCard[];
  page: number;
  limit: number;
  total: number;
}

export interface PublicMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  input_mode: "text" | "voice";
  created_at: string;
}

export interface PublicChatResponse {
  session_id: string;
  expires_at: string;
  message: PublicMessage;
  sources: { title: string }[];
  messages_left: number;
}

export interface PublicSession {
  expires_at: string;
  messages: PublicMessage[];
  messages_left: number;
}

export interface PublicJob {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  video_url: string | null;
  error_message: string | null;
}

export interface PublicSettings {
  slug: string;
  visibility: Visibility;
  public_chat_enabled: boolean;
  public_voice_enabled: boolean;
  public_avatar_enabled: boolean;
  voice_available: boolean;
  avatar_available: boolean;
  public_document_count: number;
  public_memory_count: number;
  share_path: string;
  share_url: string;
}

export type PublicSettingsUpdate = Partial<
  Pick<PublicSettings, "visibility" | "public_chat_enabled" | "public_voice_enabled" | "public_avatar_enabled">
>;
