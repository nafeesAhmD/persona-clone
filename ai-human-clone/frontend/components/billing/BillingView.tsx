"use client";

import { useState } from "react";

import { Card, Collapsible, LoadingBlock, Notice, PageShell, UsageMeter, btnDanger, btnPrimary, btnSecondary, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { billingApi } from "@/lib/billingApi";
import {
  describeUsage,
  formatPrice,
  formatResetDate,
  formatUsage,
  planLimitLines,
  sortPlans,
  toneLabel,
  usagePercent,
  usageTone,
} from "@/lib/usage";
import type { Plan, Subscription, UsageItem, UsageSummary } from "@/types/billing";

interface BillingData {
  usage: UsageSummary;
  plans: Plan[];
  subscription: Subscription | null;
}

/** Usage is required; plans and the subscription are extras the page can live without. */
async function loadBilling(): Promise<BillingData> {
  const [usage, plans, subscription] = await Promise.all([
    billingApi.usage(),
    billingApi.plans().catch(() => [] as Plan[]),
    billingApi.subscription().catch(() => null),
  ]);
  return { usage, plans, subscription };
}

const DISABLED_REASON = "Billing is not enabled on this server, so plans can't be changed. Everyone uses the free limits.";

function UsageRow({ item }: { item: UsageItem }) {
  const tone = usageTone(item.used, item.limit);
  return (
    <li>
      <UsageMeter
        label={item.label}
        percent={usagePercent(item.used, item.limit)}
        text={formatUsage(item.used, item.limit, item.unit)}
        tone={tone}
        toneText={toneLabel(tone)}
      />
      <span className="sr-only">{describeUsage(item)}</span>
    </li>
  );
}

export function BillingView() {
  const { data, error, reload } = useApiData(loadBilling, "billing");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "error" | "success" | "info"; text: string } | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  if (error && !data) return <ApiErrorState error={error} thing="billing page" onRetry={reload} />;

  const usage = data?.usage;
  const enabled = usage?.billing_enabled ?? false;
  const monthly = usage?.items.filter((i) => i.period === "month") ?? [];
  const totalsItems = usage?.items.filter((i) => i.period === "total") ?? [];
  const reset = formatResetDate(usage?.reset_at);
  const plans = sortPlans(data?.plans ?? []);
  const isPaid = !!usage && usage.plan_slug !== "free";
  const status = data?.subscription?.status;

  async function upgrade(plan: Plan) {
    setBusy(plan.slug);
    setNotice(null);
    try {
      const { url } = await billingApi.checkout(plan.slug);
      if (url) {
        window.location.assign(url);
        return;
      }
      setNotice({ tone: "info", text: "Checkout isn't available yet on this server. Please try again later." });
    } catch (err) {
      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't start checkout." });
    } finally {
      setBusy(null);
    }
  }

  async function cancelPlan() {
    setBusy("cancel");
    setCancelError(null);
    try {
      await billingApi.cancel();
      setConfirmCancel(false);
      setNotice({ tone: "success", text: "Your subscription was cancelled." });
      reload();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : "Couldn't cancel the subscription.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <PageShell title="Billing" description="Your plan, what you've used, and what's included.">
      {!data || !usage ? (
        <LoadingBlock label="Loading billing…" />
      ) : (
        <div className="space-y-4">
          {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}

          <Card>
            <p className="text-xs uppercase tracking-wide text-muted">Current plan</p>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-2xl font-semibold text-white">{usage.plan_name}</h2>
              {status && (
                <span className="rounded-full border border-border px-2 py-0.5 text-xs capitalize text-gray-200">{status}</span>
              )}
            </div>
            {reset && <p className="mt-2 text-sm text-gray-200">Monthly usage {reset.charAt(0).toLowerCase() + reset.slice(1)}.</p>}
            {!enabled && (
              <p className="mt-3 rounded-xl border border-border bg-surface px-3 py-2 text-sm text-muted">{DISABLED_REASON}</p>
            )}
            {enabled && isPaid && status !== "cancelled" && (
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <button
                  type="button"
                  className={btnSecondary}
                  disabled={busy !== null}
                  onClick={async () => {
                    setBusy("portal");
                    try {
                      const { url } = await billingApi.portal();
                      if (url) window.location.assign(url);
                      else setNotice({ tone: "info", text: "The billing portal isn't available yet on this server." });
                    } catch (err) {
                      setNotice({ tone: "error", text: err instanceof Error ? err.message : "Couldn't open the billing portal." });
                    } finally {
                      setBusy(null);
                    }
                  }}
                >
                  Manage payment details
                </button>
                <button type="button" className={btnDanger} disabled={busy !== null} onClick={() => setConfirmCancel(true)}>
                  Cancel subscription
                </button>
              </div>
            )}
          </Card>

          <Collapsible title="This month's usage" meta={reset ?? undefined}>
            {monthly.length === 0 ? (
              <p className="text-sm text-muted">No monthly limits on your plan.</p>
            ) : (
              <ul className="space-y-4">
                {monthly.map((item) => (
                  <UsageRow key={item.key} item={item} />
                ))}
              </ul>
            )}
          </Collapsible>

          <Collapsible title="Totals" meta="not reset monthly">
            <ul className="space-y-4">
              {totalsItems.map((item) => (
                <UsageRow key={item.key} item={item} />
              ))}
            </ul>
          </Collapsible>

          <Collapsible title="Plans" defaultOpen={!isPaid}>
            {plans.length === 0 ? (
              <p className="text-sm text-muted">No plans are available.</p>
            ) : (
              <ul className="grid grid-cols-1 gap-3 md:grid-cols-3">
                {plans.map((plan) => {
                  const current = plan.slug === usage.plan_slug;
                  const reasonId = `plan-${plan.slug}-reason`;
                  return (
                    <li key={plan.slug} className={`flex flex-col rounded-2xl border p-4 ${current ? "border-accent bg-accent/10" : "border-border bg-surface"}`}>
                      <div className="flex items-baseline justify-between gap-2">
                        <h3 className="font-semibold text-white">{plan.name}</h3>
                        {current && <span className="rounded-full bg-accent/30 px-2 py-0.5 text-xs text-white">Your plan</span>}
                      </div>
                      <p className="mt-1 text-lg font-semibold text-white">{formatPrice(plan)}</p>
                      {plan.description && <p className="mt-1 text-sm text-muted">{plan.description}</p>}
                      <ul className="mt-3 flex-1 space-y-1 text-sm text-gray-200">
                        {planLimitLines(plan.limits).map((line) => (
                          <li key={line} className="flex gap-2">
                            <span aria-hidden="true" className="text-accent-soft">✓</span>
                            {line}
                          </li>
                        ))}
                      </ul>
                      {!current && plan.price > 0 && (
                        <div className="mt-4">
                          <button
                            type="button"
                            className={`${btnPrimary} w-full`}
                            disabled={!enabled || busy !== null}
                            aria-describedby={!enabled ? reasonId : undefined}
                            onClick={() => upgrade(plan)}
                          >
                            {busy === plan.slug ? "Starting checkout…" : `Upgrade to ${plan.name}`}
                          </button>
                          {!enabled && (
                            <p id={reasonId} className="mt-2 text-xs text-muted">
                              Billing is not enabled on this server.
                            </p>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Collapsible>

          <p className="text-xs text-muted">Payments are handled by the payment provider. This app never shows or stores card details.</p>
        </div>
      )}

      <ConfirmDialog
        open={confirmCancel}
        title="Cancel your subscription?"
        message="Your plan stops renewing. When it ends you'll move to the free limits; anything above them stays but you can't add more."
        confirmLabel="Cancel subscription"
        busyLabel="Cancelling…"
        busy={busy === "cancel"}
        error={cancelError}
        onConfirm={cancelPlan}
        onCancel={() => {
          setConfirmCancel(false);
          setCancelError(null);
        }}
      />
    </PageShell>
  );
}
