"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, LoadingBlock, Notice, PageShell, btnDanger, btnPrimary, inputCls, labelCls } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { InactiveNote, OrgTabs, memberName, useOrg } from "@/components/organizations/shared";
import { orgApi } from "@/lib/orgApi";
import { canDeactivate, canEditSettings, canLeave, canTransferOwnership, orgErrorMessage, sortMembers } from "@/lib/orgRoles";
import type { Organization } from "@/types/organizations";

type Danger = "leave" | "transfer" | "deactivate" | null;

function DetailsForm({ org, editable, onSaved }: { org: Organization; editable: boolean; onSaved: (org: Organization) => void }) {
  const [name, setName] = useState(org.name);
  const [description, setDescription] = useState(org.description ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const changed = name.trim() !== org.name || description.trim() !== (org.description ?? "");

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setMessage({ tone: "error", text: "The name can't be empty." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const updated = await orgApi.update(org.id, { name: name.trim(), description: description.trim() });
      onSaved(updated);
      setMessage({ tone: "success", text: "Saved." });
    } catch (err) {
      setMessage({ tone: "error", text: orgErrorMessage(err, "Couldn't save the changes.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-white">Details</h2>
      <form onSubmit={save} className="space-y-4" noValidate>
        <div>
          <label htmlFor="settings-name" className={labelCls}>
            Name
          </label>
          <input
            id="settings-name"
            className={inputCls}
            value={name}
            maxLength={160}
            readOnly={!editable}
            autoComplete="organization"
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="settings-description" className={labelCls}>
            Description
          </label>
          <textarea
            id="settings-description"
            className={`${inputCls} min-h-24 py-2`}
            value={description}
            maxLength={500}
            rows={3}
            readOnly={!editable}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        {message && <Notice tone={message.tone}>{message.text}</Notice>}
        {editable ? (
          <button type="submit" className={`${btnPrimary} w-full sm:w-auto`} disabled={busy || !changed}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        ) : (
          <p className="text-xs text-muted">Only the owner and admins can change these.</p>
        )}
      </form>
    </Card>
  );
}

export function OrgSettings({ orgId }: { orgId: string }) {
  const router = useRouter();
  const { org, members, role, userId, error, reload, data, setData } = useOrg(orgId);
  const [danger, setDanger] = useState<Danger>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (error && !org) return <ApiErrorState error={error} thing="organization" onRetry={reload} />;
  if (!org || !data) {
    return (
      <PageShell title="Settings" back={{ href: "/organizations", label: "Organizations" }}>
        <LoadingBlock label="Loading settings…" />
      </PageShell>
    );
  }

  const others = sortMembers(members).filter((m) => m.user_id !== userId);
  const chosen = target || others[0]?.user_id || "";
  const chosenMember = others.find((m) => m.user_id === chosen);

  async function run() {
    setBusy(true);
    setDialogError(null);
    try {
      if (danger === "leave") {
        await orgApi.leave(orgId);
        router.push("/organizations");
        return;
      }
      if (danger === "deactivate") {
        await orgApi.deactivate(orgId);
        router.push("/organizations");
        return;
      }
      if (danger === "transfer" && chosen) {
        await orgApi.transferOwnership(orgId, chosen);
        setDanger(null);
        setNotice(`Ownership was transferred to ${chosenMember ? memberName(chosenMember) : "the member"}. You're now an admin.`);
        reload();
      }
    } catch (err) {
      setDialogError(orgErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const dialog = {
    leave: {
      title: `Leave ${org.name}?`,
      message: "You lose access to the organization and its clones. You'd need a new invitation to come back.",
      confirm: "Leave organization",
      busy: "Leaving…",
    },
    transfer: {
      title: "Transfer ownership?",
      message: `${chosenMember ? memberName(chosenMember) : "This member"} becomes the owner. You become an admin and can't undo this yourself.`,
      confirm: "Transfer ownership",
      busy: "Transferring…",
    },
    deactivate: {
      title: `Deactivate ${org.name}?`,
      message: "The organization is turned off for everyone: members lose access and pending invitations stop working.",
      confirm: "Deactivate organization",
      busy: "Deactivating…",
    },
  };
  const current = danger ? dialog[danger] : null;

  return (
    <PageShell title="Settings" description={org.name} back={{ href: `/organizations/${encodeURIComponent(org.id)}`, label: org.name }}>
      <OrgTabs org={org} />
      <InactiveNote org={org} />
      <div className="space-y-4">
        {notice && <Notice tone="success">{notice}</Notice>}
        <DetailsForm
          key={org.updated_at}
          org={org}
          editable={canEditSettings(role) && org.is_active}
          onSaved={(updated) => setData({ ...data, org: updated })}
        />

        <section aria-labelledby="danger-heading" className="rounded-2xl border border-rose-500/30 p-4">
          <h2 id="danger-heading" className="text-sm font-semibold text-rose-200">
            Danger zone
          </h2>
          <div className="mt-3 space-y-5">
            {canTransferOwnership(role) && (
              <div>
                <h3 className="text-sm font-medium text-white">Transfer ownership</h3>
                <p className="mt-1 text-sm text-muted">Make another active member the owner. Owners must do this before they can leave.</p>
                {others.length === 0 ? (
                  <p className="mt-2 text-sm text-muted">Invite a member first.</p>
                ) : (
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                    <label htmlFor="transfer-target" className="sr-only">
                      New owner
                    </label>
                    <select id="transfer-target" className={inputCls} value={chosen} onChange={(e) => setTarget(e.target.value)}>
                      {others.map((m) => (
                        <option key={m.user_id} value={m.user_id}>
                          {memberName(m)}
                        </option>
                      ))}
                    </select>
                    <button type="button" className={`${btnDanger} shrink-0`} onClick={() => setDanger("transfer")}>
                      Transfer…
                    </button>
                  </div>
                )}
              </div>
            )}

            {canLeave(role) && (
              <div>
                <h3 className="text-sm font-medium text-white">Leave organization</h3>
                <p className="mt-1 text-sm text-muted">Stop being a member of {org.name}.</p>
                <button type="button" className={`${btnDanger} mt-2 w-full sm:w-auto`} onClick={() => setDanger("leave")}>
                  Leave…
                </button>
              </div>
            )}
            {role === "owner" && <p className="text-sm text-muted">As the owner you can&apos;t leave. Transfer ownership first.</p>}

            {canDeactivate(role) && org.is_active && (
              <div>
                <h3 className="text-sm font-medium text-white">Deactivate organization</h3>
                <p className="mt-1 text-sm text-muted">Turn the organization off for everyone. Clones aren&apos;t deleted.</p>
                <button type="button" className={`${btnDanger} mt-2 w-full sm:w-auto`} onClick={() => setDanger("deactivate")}>
                  Deactivate…
                </button>
              </div>
            )}
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={!!current}
        title={current?.title ?? ""}
        message={current?.message ?? ""}
        confirmLabel={current?.confirm ?? "Confirm"}
        busyLabel={current?.busy}
        busy={busy}
        error={dialogError}
        onConfirm={run}
        onCancel={() => {
          setDanger(null);
          setDialogError(null);
        }}
      />
    </PageShell>
  );
}
