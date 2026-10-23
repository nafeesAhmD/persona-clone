"use client";

import { useEffect, useRef, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  Badge,
  ErrorNote,
  Loading,
  PageHeader,
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
import type { ApiKey, ApiKeyCreated, OrganizationOption, ScopeInfo } from "@/types/developer";

type Action = { kind: "rotate" | "revoke" | "delete"; key: ApiKey };

const STATUS_COLOR = { active: "green", revoked: "red", expired: "amber" } as const;

const ACTION_TEXT = {
  rotate: {
    title: "Rotate this key?",
    message: "A new secret is created and the current one stops working immediately. Update your apps with the new key.",
    confirm: "Rotate key",
  },
  revoke: {
    title: "Revoke this key?",
    message: "Apps using this key will stop working immediately. This can't be undone.",
    confirm: "Revoke key",
  },
  delete: {
    title: "Delete this key?",
    message: "The key is removed from your list and stops working immediately. This can't be undone.",
    confirm: "Delete key",
  },
};

export default function DeveloperKeysPage() {
  const { data: keys, error, loading, reload } = useAdminData(() => developerApi.keys(), []);
  const { data: scopes } = useAdminData(() => developerApi.scopes(), []);
  const orgs = useOrganizations();
  const [creating, setCreating] = useState(false);
  // A new dialog instance (fresh, empty form) every time it opens.
  const [dialogVersion, setDialogVersion] = useState(0);
  // The full key, kept only in memory until the user hides it.
  const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const orgName = (orgId: string | null) => orgs.find((o) => o.id === orgId)?.name ?? "Organization";

  async function runAction() {
    if (!action) return;
    setBusy(true);
    setActionError(null);
    try {
      if (action.kind === "rotate") {
        const rotated = await developerApi.rotateKey(action.key.id);
        setRevealed(rotated);
        setNotice(null);
      } else if (action.kind === "revoke") {
        await developerApi.revokeKey(action.key.id);
        setNotice(`"${action.key.name}" was revoked.`);
      } else {
        await developerApi.deleteKey(action.key.id);
        setNotice(`"${action.key.name}" was deleted.`);
      }
      setAction(null);
      reload();
    } catch (err) {
      setActionError(errorText(err, "Couldn't update the key."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="API keys" description="Keys let your apps call the developer API. Give each key only the scopes it needs.">
        <button
          type="button"
          className="min-h-11 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-ink hover:bg-accent/90 md:min-h-0"
          onClick={() => {
            setDialogVersion((v) => v + 1);
            setCreating(true);
          }}
        >
          Create API key
        </button>
      </PageHeader>

      {revealed && (
        <SecretOnce
          title={`Your API key "${revealed.name}"`}
          secret={revealed.key}
          note="Copy this key now. You will not be able to see it again."
          onDone={() => setRevealed(null)}
        />
      )}
      <SuccessNote message={notice} />
      <ErrorNote message={error} />

      {loading && !keys && <Loading />}
      {keys && (
        <Table head={["Name", "Key", "Status", "Scopes", "Last used", "Expires", ""]} empty={keys.length === 0}>
          {keys.map((key) => (
            <tr key={key.id}>
              <td className="px-3 py-2">
                <span className="block font-medium text-white">{key.name}</span>
                <span className="text-xs text-muted">
                  {key.owner_type === "organization" ? orgName(key.organization_id) : "Personal"} · created{" "}
                  {formatDate(key.created_at)}
                </span>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-white">{key.key_prefix}…</td>
              <td className="px-3 py-2">
                <Badge color={STATUS_COLOR[key.status]}>{key.status}</Badge>
              </td>
              <td className="px-3 py-2">
                <div className="flex max-w-xs flex-wrap gap-1">
                  {key.scopes.map((scope) => (
                    <Badge key={scope} color="blue">
                      {scope}
                    </Badge>
                  ))}
                </div>
              </td>
              <td className="px-3 py-2 text-muted">{key.last_used_at ? formatDate(key.last_used_at) : "Never"}</td>
              <td className="px-3 py-2 text-muted">{key.expires_at ? formatDate(key.expires_at) : "Never"}</td>
              <td className="px-3 py-2">
                <div className="flex justify-end gap-2">
                  {key.status !== "revoked" && (
                    <button
                      type="button"
                      className={buttonClass}
                      aria-label={`Rotate ${key.name}`}
                      onClick={() => { setActionError(null); setAction({ kind: "rotate", key }); }}
                    >
                      Rotate
                    </button>
                  )}
                  {key.status !== "revoked" && (
                    <button
                      type="button"
                      className={dangerButtonClass}
                      aria-label={`Revoke ${key.name}`}
                      onClick={() => { setActionError(null); setAction({ kind: "revoke", key }); }}
                    >
                      Revoke
                    </button>
                  )}
                  <button
                    type="button"
                    className={dangerButtonClass}
                    aria-label={`Delete ${key.name}`}
                    onClick={() => { setActionError(null); setAction({ kind: "delete", key }); }}
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      )}

      <CreateKeyDialog
        key={dialogVersion}
        open={creating}
        scopes={scopes ?? []}
        orgs={orgs}
        onClose={() => setCreating(false)}
        onCreated={(created) => {
          setCreating(false);
          setNotice(null);
          setRevealed(created);
          reload();
        }}
      />

      <ConfirmDialog
        open={action !== null}
        title={action ? ACTION_TEXT[action.kind].title : ""}
        message={action ? `${action.key.name} (${action.key.key_prefix}…): ${ACTION_TEXT[action.kind].message}` : ""}
        confirmLabel={action ? ACTION_TEXT[action.kind].confirm : ""}
        busy={busy}
        error={actionError}
        onConfirm={runAction}
        onCancel={() => setAction(null)}
      />
    </>
  );
}

const EXPIRY_OPTIONS = [
  { value: "none", label: "Never" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "1 year" },
  { value: "date", label: "Custom date" },
];

function expiryFrom(choice: string, date: string): string | null {
  if (choice === "none") return null;
  if (choice === "date") return date ? new Date(`${date}T23:59:59`).toISOString() : null;
  return new Date(Date.now() + Number(choice) * 86_400_000).toISOString();
}

function CreateKeyDialog({
  open,
  scopes,
  orgs,
  onClose,
  onCreated,
}: {
  open: boolean;
  scopes: ScopeInfo[];
  orgs: OrganizationOption[];
  onClose: () => void;
  onCreated: (key: ApiKeyCreated) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("90");
  const [date, setDate] = useState("");
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  function toggle(scope: string) {
    setSelected((current) => (current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope]));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return setError("Give the key a name.");
    if (selected.length === 0) return setError("Choose at least one scope.");
    if (expiry === "date" && !date) return setError("Choose an expiry date.");
    setBusy(true);
    setError(null);
    try {
      const created = await developerApi.createKey({
        name: name.trim(),
        scopes: selected,
        expires_at: expiryFrom(expiry, date),
        organization_id: org || null,
      });
      onCreated(created);
    } catch (err) {
      setError(errorText(err, "Couldn't create the key."));
    } finally {
      setBusy(false);
    }
  }

  const [tomorrow] = useState(() => new Date(Date.now() + 86_400_000).toISOString().slice(0, 10));

  return (
    <dialog
      ref={ref}
      aria-labelledby="create-key-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl border border-border bg-surface-raised p-6 text-gray-100 backdrop:bg-black/70"
    >
      <form onSubmit={submit} className="space-y-4">
        <h2 id="create-key-title" className="text-lg font-semibold">
          Create API key
        </h2>
        <div>
          <label htmlFor="key-name" className="mb-1 block text-sm text-muted">
            Name
          </label>
          <input
            id="key-name"
            className={`${inputClass} w-full`}
            value={name}
            maxLength={100}
            placeholder="e.g. Website chatbot"
            autoComplete="off"
            enterKeyHint="done"
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <fieldset>
          <legend className="mb-1 text-sm text-muted">Scopes</legend>
          {scopes.length === 0 ? (
            <p className="text-sm text-muted">Loading scopes…</p>
          ) : (
            <ul className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-border p-2">
              {scopes.map((s) => (
                <li key={s.scope}>
                  <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded px-1 py-2 hover:bg-surface">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                      checked={selected.includes(s.scope)}
                      onChange={() => toggle(s.scope)}
                    />
                    <span>
                      <span className="block font-mono text-xs text-white">{s.scope}</span>
                      <span className="text-xs text-muted">{s.description}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="key-expiry" className="mb-1 block text-sm text-muted">
              Expires
            </label>
            <select id="key-expiry" className={`${inputClass} w-full`} value={expiry} onChange={(e) => setExpiry(e.target.value)}>
              {EXPIRY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          {expiry === "date" && (
            <div>
              <label htmlFor="key-expiry-date" className="mb-1 block text-sm text-muted">
                Expiry date
              </label>
              <input
                id="key-expiry-date"
                type="date"
                min={tomorrow}
                className={`${inputClass} w-full`}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
          )}
        </div>
        {orgs.length > 0 && (
          <div>
            <label htmlFor="key-owner" className="mb-1 block text-sm text-muted">
              Owner
            </label>
            <select id="key-owner" className={`${inputClass} w-full`} value={org} onChange={(e) => setOrg(e.target.value)}>
              <option value="">Personal key</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} (organization key)
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-muted">Only organization owners and admins can create organization keys.</p>
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-rose-300">
            {error}
          </p>
        )}
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button type="button" className={buttonClass} onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="min-h-11 rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-ink hover:bg-accent/90 disabled:opacity-60 md:min-h-0"
          >
            {busy ? "Creating…" : "Create key"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
