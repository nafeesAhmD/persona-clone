import { ApiError, apiFetch } from "@/lib/api";
import type { Plan, Subscription, UsageSummary } from "@/types/billing";

/** Billing for the signed-in user. Checkout/cancel/portal answer 403 while billing is disabled. */
export const billingApi = {
  plans(): Promise<Plan[]> {
    return apiFetch<Plan[]>("/api/billing/plans", { cache: "no-store" });
  },
  /** The current subscription, or null when there is none (e.g. plans not set up on this server). */
  async subscription(): Promise<Subscription | null> {
    try {
      return await apiFetch<Subscription>("/api/billing/subscription", { cache: "no-store" });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
  usage(): Promise<UsageSummary> {
    return apiFetch<UsageSummary>("/api/billing/usage", { cache: "no-store" });
  },
  checkout(planSlug: string): Promise<{ url: string | null }> {
    return apiFetch<{ url: string | null }>("/api/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan: planSlug }),
    });
  },
  cancel(): Promise<{ status: string }> {
    return apiFetch<{ status: string }>("/api/billing/cancel", { method: "POST" });
  },
  portal(): Promise<{ url: string | null }> {
    return apiFetch<{ url: string | null }>("/api/billing/portal", { method: "POST" });
  },
};
