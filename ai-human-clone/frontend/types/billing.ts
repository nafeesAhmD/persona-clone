/** A plan (GET /api/billing/plans). Limits of 0 or missing mean unlimited. */
export interface Plan {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  price: number;
  currency: string;
  billing_interval: string;
  is_active: boolean;
  is_public: boolean;
  limits: Record<string, number>;
  features: Record<string, boolean>;
}

/** GET /api/billing/subscription. No payment-provider ids are ever sent. */
export interface Subscription {
  id: string;
  user_id: string;
  plan_id: string;
  provider: string | null;
  status: string;
  billing_cycle: string;
  started_at: string;
  current_period_start: string | null;
  current_period_end: string | null;
  cancelled_at: string | null;
}

export interface UsageItem {
  key: string;
  label: string;
  used: number;
  /** null: unlimited. */
  limit: number | null;
  /** "month": resets on reset_at; "total": a running total. */
  period: "month" | "total";
  unit: string | null;
}

/** GET /api/billing/usage. */
export interface UsageSummary {
  plan_slug: string;
  plan_name: string;
  billing_enabled: boolean;
  period_start: string | null;
  reset_at: string | null;
  items: UsageItem[];
}
