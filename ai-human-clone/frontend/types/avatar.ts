export type AvatarType = "uploaded" | "generated" | "preset";
export type AvatarStatus = "pending" | "processing" | "ready" | "failed";
export type AvatarJobStatus = "queued" | "processing" | "completed" | "failed" | "cancelled";

export interface CloneAvatar {
  id: string;
  clone_id: string;
  avatar_type: AvatarType;
  status: AvatarStatus;
  is_active: boolean;
  width: number;
  height: number;
  /** Mouth centre and width, as fractions of the image. */
  mouth_x: number;
  mouth_y: number;
  mouth_width: number;
  face_detected: boolean;
  error_message: string | null;
  /** API path; fetched with the session cookie (owner only). */
  image_url: string;
  created_at: string;
  updated_at: string;
}

export interface AvatarSettings {
  avatar_enabled: boolean;
  avatar_consent_given: boolean;
  avatar_consent_at: string | null;
  active_avatar: CloneAvatar | null;
  avatars: CloneAvatar[];
  presets: { id: string; name: string }[];
  /** null when avatar videos are turned off on the server. */
  lipsync_provider: string | null;
  voice_enabled: boolean;
  max_video_seconds: number;
}

export interface AvatarSettingsUpdate {
  avatar_enabled?: boolean;
  avatar_consent_given?: boolean;
  active_avatar_id?: string;
  mouth_x?: number;
  mouth_y?: number;
  mouth_width?: number;
}

export interface AvatarStyle {
  skin: string;
  hair: string;
  hair_style: "short" | "long" | "bun" | "none";
  background: string;
  shirt: string;
}

export interface AvatarJob {
  job_id: string;
  status: AvatarJobStatus;
  progress: number;
  video_url: string | null;
  expired: boolean;
  error_message: string | null;
  duration_seconds: number | null;
  conversation_id: string | null;
  message_id: string | null;
  provider: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
