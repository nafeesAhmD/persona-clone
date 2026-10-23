import { apiFetch } from "@/lib/api";
import type { Page } from "@/types/admin";
import type {
  AdminApiKeyRow,
  AdminDeveloperOverview,
  ApiKey,
  ApiKeyCreatePayload,
  ApiKeyCreated,
  ApiKeyUpdatePayload,
  DeliveryPage,
  DeveloperOverview,
  DeveloperUsage,
  OrganizationOption,
  ScopeInfo,
  Webhook,
  WebhookCreatePayload,
  WebhookDelivery,
  WebhookEventInfo,
  WebhookTestResult,
  WebhookUpdatePayload,
  WebhookWithSecret,
} from "@/types/developer";

/**
 * Developer dashboard calls (cookie session). The server checks ownership on every
 * request; nothing here ever receives a stored key or secret again after creation.
 */

type Query = Record<string, string | number | null | undefined>;

function withQuery(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

const id = (value: string) => encodeURIComponent(value);
const get = <T,>(path: string, query?: Query) => apiFetch<T>(withQuery(path, query), { cache: "no-store" });
const send = <T,>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown) =>
  apiFetch<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const developerApi = {
  // Keys
  keys: () => get<ApiKey[]>("/api/developer/keys"),
  scopes: () => get<ScopeInfo[]>("/api/developer/keys/scopes"),
  createKey: (payload: ApiKeyCreatePayload) => send<ApiKeyCreated>("POST", "/api/developer/keys", payload),
  updateKey: (keyId: string, payload: ApiKeyUpdatePayload) =>
    send<ApiKey>("PATCH", `/api/developer/keys/${id(keyId)}`, payload),
  rotateKey: (keyId: string) => send<ApiKeyCreated>("POST", `/api/developer/keys/${id(keyId)}/rotate`),
  revokeKey: (keyId: string) => send<ApiKey>("POST", `/api/developer/keys/${id(keyId)}/revoke`),
  deleteKey: (keyId: string) => send<void>("DELETE", `/api/developer/keys/${id(keyId)}`),

  // Webhooks
  webhookEvents: () => get<WebhookEventInfo[]>("/api/developer/webhooks/events"),
  webhooks: () => get<Webhook[]>("/api/developer/webhooks"),
  createWebhook: (payload: WebhookCreatePayload) => send<WebhookWithSecret>("POST", "/api/developer/webhooks", payload),
  updateWebhook: (hookId: string, payload: WebhookUpdatePayload) =>
    send<Webhook>("PATCH", `/api/developer/webhooks/${id(hookId)}`, payload),
  deleteWebhook: (hookId: string) => send<void>("DELETE", `/api/developer/webhooks/${id(hookId)}`),
  rotateWebhookSecret: (hookId: string) =>
    send<WebhookWithSecret>("POST", `/api/developer/webhooks/${id(hookId)}/rotate-secret`),
  testWebhook: (hookId: string) => send<WebhookTestResult>("POST", `/api/developer/webhooks/${id(hookId)}/test`),
  deliveries: (hookId: string, page = 1, limit = 10) =>
    get<DeliveryPage>(`/api/developer/webhooks/${id(hookId)}/deliveries`, { page, limit }),
  retryDelivery: (hookId: string, deliveryId: string) =>
    send<WebhookDelivery>("POST", `/api/developer/webhooks/${id(hookId)}/deliveries/${id(deliveryId)}/retry`),

  // Dashboard
  overview: (organizationId?: string) =>
    get<DeveloperOverview>("/api/developer/overview", { organization_id: organizationId }),
  usage: (days: number, organizationId?: string) =>
    get<DeveloperUsage>("/api/developer/usage", { days, organization_id: organizationId }),

  /** Organizations the user belongs to; only owners/admins can manage their keys (the server checks). */
  organizations: () => get<OrganizationOption[]>("/api/organizations/"),
};

export const adminDeveloperApi = {
  overview: () => get<AdminDeveloperOverview>("/api/admin/developer/overview"),
  keys: (query: { page: number; limit: number; search?: string; status?: string }) =>
    get<Page<AdminApiKeyRow>>("/api/admin/developer/keys", query),
  revokeKey: (keyId: string, reason?: string) =>
    send<AdminApiKeyRow>("POST", `/api/admin/developer/keys/${id(keyId)}/revoke`, reason ? { reason } : {}),
};
