"use client";

import Link from "next/link";
import { useState } from "react";

import {
  Card,
  Collapsible,
  EmptyState,
  LoadingBlock,
  Notice,
  PageShell,
  Sheet,
  UsageMeter,
  btnDanger,
  btnPrimary,
  btnSecondary,
  inputCls,
  labelCls,
  useApiData,
} from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { InactiveNote, OrgTabs, RoleBadge, memberName, useOrg } from "@/components/organizations/shared";
import { getMyClones } from "@/lib/api";
import { orgApi } from "@/lib/orgApi";
import { canAssignClones, canShareClones, canUnassignClone, orgErrorMessage, sortMembers } from "@/lib/orgRoles";
import { formatUsage, toneLabel, usagePercent, usageTone } from "@/lib/usage";
import type { CloneShareRole, OrgClone, OrgMember, UsedLimit } from "@/types/organizations";

type Feedback = { tone: "error" | "success"; text: string } | null;

function ShareSheet({
  orgId,
  clone,
  members,
  onClose,
  onDone,
}: {
  orgId: string;
  clone: OrgClone | null;
  members: OrgMember[];
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const candidates = sortMembers(members).filter((m) => m.user_id !== clone?.owner_id);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<CloneShareRole>("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = userId || candidates[0]?.user_id || "";

  async function run(action: "share" | "unshare") {
    if (!clone || !selected) return;
    setBusy(true);
    setError(null);
    try {
      const who = memberName(candidates.find((m) => m.user_id === selected)!);
      if (action === "share") {
        await orgApi.shareClone(orgId, clone.id, selected, role);
        onDone(`${who} now has ${role} access to ${clone.name}.`);
      } else {
        await orgApi.unshareClone(orgId, clone.id, selected);
        onDone(`${who}'s extra access to ${clone.name} was removed.`);
      }
    } catch (err) {
      setError(orgErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={!!clone} title={clone ? `Share ${clone.name}` : "Share clone"} onClose={onClose} busy={busy}>
      {candidates.length === 0 ? (
        <p className="text-sm text-muted">Invite members first; then you can give them access to this clone.</p>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">Give one member a role on this clone, on top of their organization role.</p>
          <div>
            <label htmlFor="share-member" className={labelCls}>
              Member
            </label>
            <select id="share-member" className={inputCls} value={selected} onChange={(e) => setUserId(e.target.value)}>
              {candidates.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {memberName(m)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="share-role" className={labelCls}>
              Access
            </label>
            <select id="share-role" className={inputCls} value={role} onChange={(e) => setRole(e.target.value as CloneShareRole)}>
              <option value="viewer">Viewer — can view</option>
              <option value="editor">Editor — can edit</option>
              <option value="owner">Full access</option>
            </select>
          </div>
          {error && (
            <p role="alert" className="text-sm text-rose-300">
              {error}
            </p>
          )}
          <div className="flex flex-col gap-2 sm:flex-row-reverse">
            <button type="button" className={btnPrimary} disabled={busy} onClick={() => run("share")}>
              {busy ? "Saving…" : "Give access"}
            </button>
            <button type="button" className={btnDanger} disabled={busy} onClick={() => run("unshare")}>
              Remove access
            </button>
          </div>
        </div>
      )}
    </Sheet>
  );
}

function UsageRow({ label, value }: { label: string; value: UsedLimit }) {
  const tone = usageTone(value.used, value.limit);
  return (
    <UsageMeter
      label={label}
      percent={usagePercent(value.used, value.limit)}
      text={formatUsage(value.used, value.limit)}
      tone={tone}
      toneText={toneLabel(tone)}
    />
  );
}

export function OrgOverview({ orgId }: { orgId: string }) {
  const { org, members, role, userId, error, reload } = useOrg(orgId);
  const clones = useApiData(() => orgApi.clones(orgId), orgId);
  const myClones = useApiData(() => getMyClones().catch(() => []), "mine");
  const usage = useApiData(() => orgApi.usage(orgId).catch(() => null), orgId);
  const notes = useApiData(() => orgApi.notifications(orgId, 5).catch(() => []), orgId);

  const [feedback, setFeedback] = useState<Feedback>(null);
  const [assignId, setAssignId] = useState("");
  const [busy, setBusy] = useState(false);
  const [unassign, setUnassign] = useState<OrgClone | null>(null);
  const [unassignError, setUnassignError] = useState<string | null>(null);
  const [sharing, setSharing] = useState<OrgClone | null>(null);

  if (error && !org) return <ApiErrorState error={error} thing="organization" onRetry={reload} />;
  if (!org) {
    return (
      <PageShell title="Organization" back={{ href: "/organizations", label: "Organizations" }}>
        <LoadingBlock label="Loading organization…" />
      </PageShell>
    );
  }

  const active = sortMembers(members);
  const orgClones = clones.data ?? [];
  const inOrg = new Set(orgClones.map((c) => c.id));
  const assignable = (myClones.data ?? []).filter((c) => !inOrg.has(c.id));
  const chosen = assignId || assignable[0]?.id || "";

  async function assign(event: React.FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setFeedback(null);
    try {
      const clone = await orgApi.assignClone(orgId, chosen);
      setFeedback({ tone: "success", text: `${clone.name} was added to ${org!.name}.` });
      setAssignId("");
      clones.reload();
      usage.reload();
    } catch (err) {
      setFeedback({ tone: "error", text: orgErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  async function confirmUnassign() {
    if (!unassign) return;
    setBusy(true);
    setUnassignError(null);
    try {
      await orgApi.unassignClone(orgId, unassign.id);
      setFeedback({ tone: "success", text: `${unassign.name} was taken out of the organization.` });
      setUnassign(null);
      clones.reload();
      usage.reload();
    } catch (err) {
      setUnassignError(orgErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell
      title={org.name}
      description={org.description ?? undefined}
      back={{ href: "/organizations", label: "Organizations" }}
    >
      <OrgTabs org={org} />
      <InactiveNote org={org} />
      <div className="space-y-4">
        {feedback && <Notice tone={feedback.tone}>{feedback.text}</Notice>}

        <Card>
          <div className="flex flex-wrap items-center gap-2 text-sm text-gray-200">
            <span>Your role:</span>
            {role ? <RoleBadge role={role} /> : <span className="text-muted">not a member</span>}
          </div>
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
            <div className="rounded-xl bg-surface p-2">
              <dt className="text-xs text-muted">Members</dt>
              <dd className="text-xl font-semibold text-white">{active.length}</dd>
            </div>
            <div className="rounded-xl bg-surface p-2">
              <dt className="text-xs text-muted">Clones</dt>
              <dd className="text-xl font-semibold text-white">{clones.data ? orgClones.length : "…"}</dd>
            </div>
            <div className="rounded-xl bg-surface p-2">
              <dt className="text-xs text-muted">Messages</dt>
              <dd className="text-xl font-semibold text-white">{usage.data ? usage.data.messages.used : "—"}</dd>
            </div>
          </dl>
          <p className="mt-2 text-xs text-muted">Messages: last 30 days.</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Link href={`/organizations/${encodeURIComponent(org.id)}/members`} className={btnSecondary}>
              Members
            </Link>
            <Link href={`/organizations/${encodeURIComponent(org.id)}/settings`} className={btnSecondary}>
              Settings
            </Link>
          </div>
        </Card>

        <Collapsible title="Clones" meta={clones.data ? `${orgClones.length}` : undefined}>
          {clones.error && !clones.data ? (
            <ApiErrorState error={clones.error} thing="clones" onRetry={clones.reload} />
          ) : !clones.data ? (
            <LoadingBlock label="Loading clones…" />
          ) : orgClones.length === 0 ? (
            <p className="text-sm text-muted">No clones in this organization yet.</p>
          ) : (
            <ul className="space-y-2">
              {orgClones.map((clone) => (
                <li key={clone.id} className="rounded-xl border border-border bg-surface p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words font-medium text-white">{clone.name}</p>
                      <p className="text-xs text-muted">
                        {clone.visibility} · {clone.status}
                        {clone.owner_id === userId ? " · yours" : ""}
                      </p>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {clone.owner_id === userId && (
                      <Link href={`/clone/${encodeURIComponent(clone.id)}/analytics`} className={btnSecondary}>
                        Analytics
                      </Link>
                    )}
                    {canShareClones(role) && (
                      <button type="button" className={btnSecondary} onClick={() => setSharing(clone)}>
                        Share
                      </button>
                    )}
                    {canUnassignClone(role, clone, userId) && (
                      <button type="button" className={btnDanger} onClick={() => setUnassign(clone)}>
                        Remove
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {canAssignClones(role) && org.is_active && (
            <form onSubmit={assign} className="mt-4 border-t border-border pt-4">
              <label htmlFor="assign-clone" className={labelCls}>
                Add one of your clones
              </label>
              {assignable.length === 0 ? (
                <p className="text-sm text-muted">
                  {myClones.data ? "All your clones are already here (or you have none)." : "Loading your clones…"}
                </p>
              ) : (
                <div className="flex flex-col gap-2 sm:flex-row">
                  <select id="assign-clone" className={inputCls} value={chosen} onChange={(e) => setAssignId(e.target.value)}>
                    {assignable.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <button type="submit" className={`${btnPrimary} shrink-0`} disabled={busy || !chosen}>
                    {busy ? "Adding…" : "Add clone"}
                  </button>
                </div>
              )}
            </form>
          )}
        </Collapsible>

        {usage.data && (
          <Collapsible title={`Plan usage · ${usage.data.plan_name}`} defaultOpen={false}>
            <div className="space-y-4">
              <UsageRow label="Members" value={usage.data.members} />
              <UsageRow label="Clones" value={usage.data.clones} />
              <UsageRow label="Messages (30 days)" value={usage.data.messages} />
              <UsageRow label="Documents" value={usage.data.documents} />
            </div>
          </Collapsible>
        )}

        <Collapsible title="Recent activity" defaultOpen={false}>
          {!notes.data ? (
            <LoadingBlock label="Loading activity…" />
          ) : notes.data.length === 0 ? (
            <EmptyState title="Nothing new" body="Invitations, role changes and members joining show up here." />
          ) : (
            <>
              <ul className="divide-y divide-border">
                {notes.data.map((n) => (
                  <li key={n.id} className="py-2">
                    <p className="text-sm font-medium text-white">
                      {!n.is_read && <span className="sr-only">Unread: </span>}
                      {!n.is_read && <span aria-hidden="true" className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" />}
                      {n.title}
                    </p>
                    <p className="text-sm text-muted">{n.message}</p>
                    <p className="text-xs text-muted">{new Date(n.created_at).toLocaleString()}</p>
                  </li>
                ))}
              </ul>
              {notes.data.some((n) => !n.is_read) && (
                <button
                  type="button"
                  className={`${btnSecondary} mt-2`}
                  onClick={async () => {
                    try {
                      await orgApi.markAllRead(orgId);
                    } finally {
                      notes.reload();
                    }
                  }}
                >
                  Mark all as read
                </button>
              )}
            </>
          )}
        </Collapsible>
      </div>

      <ShareSheet
        key={sharing?.id ?? "none"}
        orgId={orgId}
        clone={sharing}
        members={members}
        onClose={() => setSharing(null)}
        onDone={(text) => {
          setSharing(null);
          setFeedback({ tone: "success", text });
        }}
      />
      <ConfirmDialog
        open={!!unassign}
        title={unassign ? `Remove ${unassign.name}?` : "Remove clone?"}
        message="The clone leaves the organization and members lose the access they had through it. The clone itself isn't deleted."
        confirmLabel="Remove from organization"
        busyLabel="Removing…"
        busy={busy && !!unassign}
        error={unassignError}
        onConfirm={confirmUnassign}
        onCancel={() => {
          setUnassign(null);
          setUnassignError(null);
        }}
      />
    </PageShell>
  );
}
