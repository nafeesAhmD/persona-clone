/** Developer platform (Phase 14). Full keys and webhook secrets appear only in the
 * "created/rotated" responses, and the UI shows them once. */

export type KeyStatus = "active" | "revoked" | "expired";
export type OwnerType = "user" | "organization";

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  owner_type: OwnerType;
  organization_id: string | null;
  status: KeyStatus;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/** Only returned by create and rotate. */
export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  expires_at?: string | null;
  organization_id?: string | null;
}

export interface ApiKeyUpdatePayload {
  name?: string;
  scopes?: string[];
  expires_at?: string | null;
}

export interface ScopeInfo {
  scope: string;
  description: string;
}

export interface WebhookEventInfo {
  event: string;
  description: string;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  is_active: boolean;
  owner_type: OwnerType;
  organization_id: string | null;
  failure_count: number;
  last_delivery_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Only returned by create and rotate-secret. */
export interface WebhookWithSecret extends Webhook {
  secret: string;
}

export interface WebhookCreatePayload {
  url: string;
  events: string[];
  organization_id?: string | null;
  is_active?: boolean;
}

export interface WebhookUpdatePayload {
  url?: string;
  events?: string[];
  is_active?: boolean;
}

export type DeliveryStatus = "pending" | "delivering" | "delivered" | "failed";

export interface WebhookDelivery {
  id: string;
  event_id: string;
  event_type: string;
  status: DeliveryStatus;
  response_status: number | null;
  attempts: number;
  last_error: string | null;
  delivered_at: string | null;
  next_retry_at: string | null;
  created_at: string;
}

export interface DeliveryPage {
  items: WebhookDelivery[];
  page: number;
  limit: number;
  total: number;
}

export interface WebhookTestResult {
  delivery_id: string;
  status: string;
}

export interface DeveloperOverview {
  plan: string;
  api_requests_30d: number;
  chat_requests_30d: number;
  successful_requests_30d: number;
  failed_requests_30d: number;
  monthly_requests: number;
  /** 0 means no monthly limit. */
  monthly_limit: number;
  rate_limit_per_minute: number;
  active_keys: number;
  active_webhooks: number;
}

export interface DeveloperUsage {
  days: number;
  per_day: { day: string; requests: number; errors: number }[];
  by_endpoint: { endpoint: string; requests: number; errors: number; avg_duration_ms: number | null }[];
  by_key: { key_id: string; name: string; key_prefix: string; requests: number }[];
}

export interface OrganizationOption {
  id: string;
  name: string;
}

// --- Admin ---

export interface AdminDeveloperOverview {
  api_requests_24h: number;
  api_requests_30d: number;
  active_keys: number;
  revoked_keys: number;
  expired_keys: number;
  active_webhooks: number;
  webhook_failures_24h: number;
  rate_limit_events_24h: number;
  api_errors_24h: number;
  top_endpoints: { endpoint: string; requests: number; errors: number }[];
  usage_by_organization: { organization_id: string; name: string; requests: number }[];
  usage_by_plan: { plan: string; requests: number }[];
}

export interface AdminApiKeyRow {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  owner_type: OwnerType;
  owner: string | null;
  user_id: string | null;
  organization_id: string | null;
  status: KeyStatus;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}
