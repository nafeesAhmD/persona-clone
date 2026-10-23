/** Admin API types. The API sends only these fields (no hashes, tokens or private content). */

export interface Page<T> {
  items: T[];
  page: number;
  limit: number;
  total: number;
}

export type HealthStatus = "healthy" | "degraded" | "unavailable" | "not_configured" | "disabled";

export interface HealthItem {
  name: string;
  status: HealthStatus;
  detail: string | null;
}

export interface DashboardStats {
  total_users: number;
  active_users: number;
  disabled_users: number;
  admin_users: number;
  total_clones: number;
  public_clones: number;
  unlisted_clones: number;
  private_clones: number;
  disabled_clones: number;
  total_documents: number;
  total_memories: number;
  total_conversations: number;
  total_messages: number;
  public_sessions: number;
  security_events_24h: number;
  errors_24h: number;
  usage_events_24h: number;
  maintenance_mode: boolean;
  health: HealthItem[];
}

export interface AdminUserRow {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  clone_count: number;
}

export interface AdminUserDetail extends AdminUserRow {
  updated_at: string;
  locked_until: string | null;
  document_count: number;
  conversation_count: number;
  message_count: number;
  memory_count: number;
}

export interface AdminCloneRow {
  id: string;
  name: string;
  slug: string;
  owner_id: string;
  owner_email: string;
  visibility: string;
  status: string;
  admin_disabled: boolean;
  public_chat_enabled: boolean;
  created_at: string;
}

export interface AdminCloneDetail extends AdminCloneRow {
  tagline: string | null;
  profession: string | null;
  public_voice_enabled: boolean;
  public_avatar_enabled: boolean;
  voice_enabled: boolean;
  avatar_enabled: boolean;
  updated_at: string;
  document_count: number;
  public_document_count: number;
  memory_count: number;
  public_memory_count: number;
  conversation_count: number;
  message_count: number;
  public_session_count: number;
}

export interface PublicCloneItem {
  id: string;
  name: string;
  slug: string;
  owner_email: string;
  visibility: string;
  status: string;
  tagline: string | null;
  profession: string | null;
  public_chat_enabled: boolean;
  created_at: string;
}

export interface PublicDocumentItem {
  id: string;
  title: string;
  clone_id: string;
  clone_name: string;
  owner_email: string;
  source_type: string;
  character_count: number;
  created_at: string;
}

export interface PublicMemoryItem {
  id: string;
  clone_id: string;
  clone_name: string;
  owner_email: string;
  memory_type: string;
  content: string;
  created_at: string;
}

export interface SecurityEventRow {
  id: string;
  event_type: string;
  severity: string;
  user_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogRow {
  id: string;
  admin_user_id: string;
  admin_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ErrorEventRow {
  id: string;
  error_type: string;
  category: string;
  method: string | null;
  endpoint: string | null;
  status_code: number;
  user_id: string | null;
  clone_id: string | null;
  message: string | null;
  location: string | null;
  created_at: string;
}

export interface UsageRow {
  event_type: string;
  provider: string | null;
  requests: number;
  failed: number;
  input_units: number;
  output_units: number;
  avg_duration_ms: number | null;
  estimated_cost: number | null;
}

export interface UsageReport {
  days: number;
  total_requests: number;
  rows: UsageRow[];
  per_day: { day: string; requests: number }[];
  top_users: { id: string; label: string; requests: number }[];
  top_clones: { id: string; label: string; requests: number }[];
  cost_configured: boolean;
  estimated_total_cost: number | null;
  note: string;
}

export interface SystemHealth {
  status: "healthy" | "degraded";
  version: string;
  environment: string;
  services: HealthItem[];
}

export type RateLimitName =
  | "login"
  | "chat"
  | "public_chat"
  | "public_voice"
  | "public_avatar"
  | "voice"
  | "avatar_video";

export interface PlatformSettings {
  maintenance_mode: boolean;
  public_registration_enabled: boolean;
  public_clone_discovery_enabled: boolean;
  public_chat_enabled: boolean;
  rate_limits: Partial<Record<RateLimitName, number>>;
  default_rate_limits: Record<RateLimitName, number>;
  updated_at: string | null;
  updated_by: string | null;
}

export interface PlatformSettingsUpdate {
  maintenance_mode?: boolean;
  public_registration_enabled?: boolean;
  public_clone_discovery_enabled?: boolean;
  public_chat_enabled?: boolean;
  rate_limits?: Partial<Record<RateLimitName, number | null>>;
}

export interface PlatformStatus {
  maintenance_mode: boolean;
  public_registration_enabled: boolean;
  public_clone_discovery_enabled: boolean;
  public_chat_enabled: boolean;
  message: string | null;
}
