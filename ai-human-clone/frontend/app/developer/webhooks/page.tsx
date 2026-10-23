"use client";

import { useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
  Pagination,
  Panel,
  SuccessNote,
  Table,
  buttonClass,
  dangerButtonClass,
  formatDate,
  inputClass,
  useAdminData,
} from "@/components/admin/ui";
import { SecretOnce, errorText, useOrganizations } from "@/components/developer/ui";
import { developerApi } from "@/lib/developerApi";
import type { DeliveryStatus, Webhook, WebhookEventInfo, WebhookWithSecret } from "@/types/developer";

type Action = { kind: "rotate" | "delete"; hook: Webhook };

const DELIVERY_COLOR: Record<DeliveryStatus, "green" | "red" | "amber" | "gray"> = {
  delivered: "green",
  failed: "red",
  pending: "amber",
  delivering: "gray",
};

export default function DeveloperWebhooksPage() {
  const { data: hooks, error, loading, reload } = useAdminData(() => developerApi.webhooks(), []);
  const { data: events } = useAdminData(() => developerApi.webhookEvents(), []);
  const orgs = useOrganizations();
  const [revealed, setRevealed] = useState<WebhookWithSecret | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [openHistory, setOpenHistory] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);

  async function runAction() {
    if (!action) return;
    setBusy(true);
    setActionError(null);
    try {
      if (action.kind === "rotate") {
        setRevealed(await developerApi.rotateWebhookSecret(action.hook.id));
        setNotice(null);
      } else {
        await developerApi.deleteWebhook(action.hook.id);
        if (openHistory === action.hook.id) setOpenHistory(null);
        setNotice("The webhook was deleted.");
      }
      setAction(null);
      reload();
    } catch (err) {
      setActionError(errorText(err, "Couldn't update the webhook."));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(hook: Webhook) {
    setRowError(null);
    try {
      await developerApi.updateWebhook(hook.id, { is_active: !hook.is_active });
      setNotice(`Webhook ${hook.is_active ? "disabled" : "enabled"}.`);
      reload();
    } catch (err) {
      setRowError(errorText(err, "Couldn't change the webhook."));
    }
  }

  async function sendTest(hook: Webhook) {
    setRowError(null);
    try {
      const result = await developerApi.testWebhook(hook.id);
      setNotice(`Test event sent (delivery ${result.status}).`);
      setOpenHistory(hook.id);
      setHistoryVersion((v) => v + 1);
      reload();
    } catch (err) {
      setRowError(errorText(err, "Couldn't send a test event."));
    }
  }

  return (
    <>
      <PageHeader
        title="Webhooks"
        description="Get an HTTPS POST when something happens: new conversations, finished videos, usage limits and more."
      />
      {revealed && (
        <SecretOnce
          title={`Signing secret for ${revealed.url}`}
          secret={revealed.secret}
          note="Copy this signing secret now. You will not be able to see it again. Use it to verify the X-AHC-Signature header."
          onDone={() => setRevealed(null)}
        />
      )}
      <SuccessNote message={notice} />
      <ErrorNote message={error ?? rowError} />

      <AddWebhookForm
        events={events ?? []}
        orgs={orgs}
        onCreated={(created) => {
          setNotice(null);
          setRevealed(created);
          reload();
        }}
      />

      {loading && !hooks && <Loading />}
      {hooks && (
        <div className="mt-6 space-y-4">
          {hooks.length === 0 && <p className="text-sm text-muted">No webhooks yet.</p>}
          {hooks.map((hook) => (
            <Panel key={hook.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="break-all font-mono text-sm text-white">{hook.url}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted">
                    <Badge color={hook.is_active ? "green" : "gray"}>{hook.is_active ? "enabled" : "disabled"}</Badge>
                    {hook.failure_count > 0 && <Badge color="red">{hook.failure_count} failed in a row</Badge>}
                    <span>
                      {hook.owner_type === "organization"
                        ? orgs.find((o) => o.id === hook.organization_id)?.name ?? "Organization"
                        : "Personal"}{" "}
                      · last delivery {hook.last_delivery_at ? formatDate(hook.last_delivery_at) : "never"}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {hook.events.map((event) => (
                      <Badge key={event} color="blue">
                        {event}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={buttonClass} onClick={() => toggleActive(hook)}>
                    {hook.is_active ? "Disable" : "Enable"}
                  </button>
                  <button type="button" className={buttonClass} onClick={() => sendTest(hook)} disabled={!hook.is_active}>
                    Send test
                  </button>
                  <button
                    type="button"
                    className={buttonClass}
                    aria-expanded={openHistory === hook.id}
                    aria-controls={`deliveries-${hook.id}`}
                    onClick={() => setOpenHistory(openHistory === hook.id ? null : hook.id)}
                  >
                    {openHistory === hook.id ? "Hide deliveries" : "Deliveries"}
                  </button>
                  <button
                    type="button"
                    className={buttonClass}
                    onClick={() => { setActionError(null); setAction({ kind: "rotate", hook }); }}
                  >
                    Rotate secret
                  </button>
                  <button
                    type="button"
                    className={dangerButtonClass}
                    onClick={() => { setActionError(null); setAction({ kind: "delete", hook }); }}
                  >
                    Delete
                  </button>
                </div>
              </div>
              {openHistory === hook.id && (
                <div id={`deliveries-${hook.id}`} className="mt-4">
                  <DeliveryHistory hookId={hook.id} version={historyVersion} />
                </div>
              )}
            </Panel>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={action !== null}
        title={action?.kind === "rotate" ? "Rotate the signing secret?" : "Delete this webhook?"}
        message={
          action?.kind === "rotate"
            ? "A new secret is created and the current one stops being used immediately. Update your server to verify with the new secret."
            : "No more events will be sent to this URL, and its delivery history is removed. This can't be undone."
        }
        confirmLabel={action?.kind === "rotate" ? "Rotate secret" : "Delete webhook"}
        busy={busy}
        error={actionError}
        onConfirm={runAction}
        onCancel={() => setAction(null)}
      />
    </>
  );
}

function AddWebhookForm({
  events,
  orgs,
  onCreated,
}: {
  events: WebhookEventInfo[];
  orgs: { id: string; name: string }[];
  onCreated: (hook: WebhookWithSecret) => void;
}) {
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(event: string) {
    setSelected((current) => (current.includes(event) ? current.filter((e) => e !== event) : [...current, event]));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^https?:\/\//i.test(url.trim())) return setError("Enter a full URL starting with https://");
    if (selected.length === 0) return setError("Choose at least one event.");
    setBusy(true);
    setError(null);
    try {
      const created = await developerApi.createWebhook({ url: url.trim(), events: selected, organization_id: org || null });
      setUrl("");
      setSelected([]);
      onCreated(created);
    } catch (err) {
      setError(errorText(err, "Couldn't add the webhook."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Add a webhook">
      <form onSubmit={submit} className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1">
            <label htmlFor="hook-url" className="mb-1 block text-sm text-muted">
              Endpoint URL
            </label>
            <input
              id="hook-url"
              type="url"
              inputMode="url"
              className={`${inputClass} w-full`}
              placeholder="https://example.com/webhooks/ai-clone"
              value={url}
              maxLength={2000}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </div>
          {orgs.length > 0 && (
            <div>
              <label htmlFor="hook-owner" className="mb-1 block text-sm text-muted">
                Owner
              </label>
              <select id="hook-owner" className={`${inputClass} w-full`} value={org} onChange={(e) => setOrg(e.target.value)}>
                <option value="">Personal</option>
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <fieldset>
          <legend className="mb-1 text-sm text-muted">Events</legend>
          {events.length === 0 ? (
            <p className="text-sm text-muted">Loading events…</p>
          ) : (
            <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {events.map((ev) => (
                <li key={ev.event}>
                  <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded px-1 py-2 hover:bg-surface">
                    <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-accent" checked={selected.includes(ev.event)} onChange={() => toggle(ev.event)} />
                    <span>
                      <span className="block font-mono text-xs text-white">{ev.event}</span>
                      <span className="text-xs text-muted">{ev.description}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        {error && (
          <p role="alert" className="text-sm text-rose-300">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="min-h-11 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-ink hover:bg-accent/90 disabled:opacity-60 md:min-h-0"
        >
          {busy ? "Adding…" : "Add webhook"}
        </button>
      </form>
    </Panel>
  );
}

const DELIVERY_LIMIT = 10;

function DeliveryHistory({ hookId, version }: { hookId: string; version: number }) {
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useAdminData(
    () => developerApi.deliveries(hookId, page, DELIVERY_LIMIT),
    [hookId, page, version],
  );
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  async function retry(deliveryId: string) {
    setRetrying(deliveryId);
    setRetryError(null);
    try {
      await developerApi.retryDelivery(hookId, deliveryId);
      reload();
    } catch (err) {
      setRetryError(errorText(err, "Couldn't retry the delivery."));
    } finally {
      setRetrying(null);
    }
  }

  return (
    <>
      <h3 className="mb-2 text-sm font-semibold text-white">Delivery history</h3>
      <ErrorNote message={error ?? retryError} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <Table head={["Event", "Status", "Response", "Attempts", "Created", "Delivered / next retry", ""]} empty={data.items.length === 0}>
            {data.items.map((d) => (
              <tr key={d.id}>
                <td className="px-3 py-2">
                  <span className="block font-mono text-xs text-white">{d.event_type}</span>
                  <span className="font-mono text-xs text-muted">{d.event_id}</span>
                </td>
                <td className="px-3 py-2">
                  <Badge color={DELIVERY_COLOR[d.status] ?? "gray"}>{d.status}</Badge>
                  {d.last_error && <span className="mt-1 block max-w-xs truncate text-xs text-rose-300" title={d.last_error}>{d.last_error}</span>}
                </td>
                <td className="px-3 py-2 text-muted">{d.response_status ?? "—"}</td>
                <td className="px-3 py-2 text-muted">{d.attempts}</td>
                <td className="px-3 py-2 text-muted">{formatDate(d.created_at)}</td>
                <td className="px-3 py-2 text-muted">
                  {d.delivered_at ? formatDate(d.delivered_at) : d.next_retry_at ? `retry ${formatDate(d.next_retry_at)}` : "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  {d.status === "failed" && (
                    <button type="button" className={buttonClass} disabled={retrying === d.id} onClick={() => retry(d.id)}>
                      {retrying === d.id ? "Retrying…" : "Retry"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          <Pagination page={data.page} limit={data.limit} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
