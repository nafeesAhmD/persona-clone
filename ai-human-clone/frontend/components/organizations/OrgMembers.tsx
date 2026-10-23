"use client";

import { useState } from "react";

import { Collapsible, LoadingBlock, Notice, PageShell, Sheet, btnDanger, btnPrimary, btnSecondary, inputCls, labelCls, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { CopyButton } from "@/components/developer/ui";
import { InactiveNote, MemberAvatar, OrgTabs, RoleBadge, memberName, useOrg } from "@/components/organizations/shared";
import { orgApi } from "@/lib/orgApi";
import {
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  assignableRoles,
  canInvite,
  canManageMember,
  inviteLink,
  orgErrorMessage,
  pendingInvitations,
  sortMembers,
  type AssignableRole,
} from "@/lib/orgRoles";
import type { OrgInvitation, OrgInvitationCreated, OrgMember, OrgRole } from "@/types/organizations";

type Feedback = { tone: "error" | "success"; text: string } | null;

function InviteSheet({
  open,
  orgId,
  orgName,
  roles,
  onClose,
  onInvited,
}: {
  open: boolean;
  orgId: string;
  orgName: string;
  roles: AssignableRole[];
  onClose: () => void;
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<AssignableRole>(roles.includes("editor") ? "editor" : roles[0] ?? "viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<OrgInvitationCreated | null>(null);
  const [shareState, setShareState] = useState<string | null>(null);

  const link = created ? inviteLink(window.location.origin, created.token) : "";
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  function close() {
    // The token lives only here: closing forgets it for good.
    setCreated(null);
    setEmail("");
    setError(null);
    setShareState(null);
    onClose();
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const value = email.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      setError("Please enter a valid email address.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setCreated(await orgApi.invite(orgId, value, role));
      onInvited();
    } catch (err) {
      setError(orgErrorMessage(err, "Couldn't create the invitation."));
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    try {
      await navigator.share({ title: `Join ${orgName}`, text: `You're invited to join ${orgName}.`, url: link });
      setShareState("Shared.");
    } catch {
      setShareState(null); // cancelled by the user
    }
  }

  return (
    <Sheet open={open} title={created ? "Invitation created" : "Invite a member"} onClose={close} busy={busy}>
      {created ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-200">
            Send this link to <span className="font-medium text-white">{created.email}</span>. They sign in with that email
            and accept. It joins them as <span className="font-medium text-white">{ROLE_LABELS[created.role]}</span> and expires on{" "}
            {new Date(created.expires_at).toLocaleDateString()}.
          </p>
          <div role="alert" className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
            This link is shown only once. Copy or share it now.
          </div>
          <label htmlFor="invite-link" className={labelCls}>
            Invite link
          </label>
          <input id="invite-link" className={`${inputCls} font-mono text-xs`} readOnly value={link} onFocus={(e) => e.target.select()} />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <CopyButton text={link} label="Copy link" className={btnPrimary} />
            {canShare && (
              <button type="button" className={btnSecondary} onClick={share}>
                Share…
              </button>
            )}
          </div>
          {shareState && <p role="status" className="text-sm text-emerald-300">{shareState}</p>}
          <button type="button" className={`${btnSecondary} w-full`} onClick={close}>
            Done
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="invite-email" className={labelCls}>
              Email
            </label>
            <input
              id="invite-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              className={inputCls}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={!!error}
              aria-describedby={error ? "invite-error" : undefined}
            />
          </div>
          <fieldset>
            <legend className={labelCls}>Role</legend>
            <div className="space-y-2">
              {roles.map((r) => (
                <label key={r} className="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border border-border p-3 has-[:checked]:border-accent">
                  <input type="radio" name="invite-role" value={r} checked={role === r} onChange={() => setRole(r)} className="mt-1 h-4 w-4 accent-accent" />
                  <span>
                    <span className="block text-sm font-medium text-white">{ROLE_LABELS[r]}</span>
                    <span className="block text-xs text-muted">{ROLE_DESCRIPTIONS[r]}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          {error && (
            <p id="invite-error" role="alert" className="text-sm text-rose-300">
              {error}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button type="button" className={btnSecondary} onClick={close} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className={btnPrimary} disabled={busy}>
              {busy ? "Creating invite…" : "Create invite link"}
            </button>
          </div>
        </form>
      )}
    </Sheet>
  );
}

function MemberCard({
  member,
  isMe,
  manageable,
  roles,
  onRole,
  onRemove,
  busy,
}: {
  member: OrgMember;
  isMe: boolean;
  manageable: boolean;
  roles: AssignableRole[];
  onRole: (role: AssignableRole) => void;
  onRemove: () => void;
  busy: boolean;
}) {
  const selectId = `role-${member.id}`;
  return (
    <li className="rounded-2xl border border-border bg-surface-raised/60 p-3">
      <div className="flex items-center gap-3">
        <MemberAvatar member={member} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-white">
            {memberName(member)}
            {isMe && <span className="ml-1 text-xs font-normal text-muted">(you)</span>}
          </p>
          {member.email && member.full_name && <p className="truncate text-xs text-muted">{member.email}</p>}
        </div>
        <RoleBadge role={member.role} />
      </div>
      {manageable && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="min-w-0 flex-1">
            <label htmlFor={selectId} className="mb-1 block text-xs text-muted">
              Change role for {memberName(member)}
            </label>
            <select
              id={selectId}
              className={inputCls}
              value={member.role}
              disabled={busy}
              onChange={(e) => onRole(e.target.value as AssignableRole)}
            >
              {/* Keep the current role selectable even if this actor can't give it. */}
              {!roles.includes(member.role as AssignableRole) && <option value={member.role}>{ROLE_LABELS[member.role]}</option>}
              {roles.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className={btnDanger} disabled={busy} onClick={onRemove}>
            Remove
          </button>
        </div>
      )}
    </li>
  );
}

export function OrgMembers({ orgId }: { orgId: string }) {
  const { org, members, role, userId, error, reload, setData, data } = useOrg(orgId);
  const manager = canInvite(role);
  const invitations = useApiData(
    () => (manager ? orgApi.invitations(orgId) : Promise.resolve([] as OrgInvitation[])),
    `${orgId}:${manager}`,
  );
  const [inviting, setInviting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [removing, setRemoving] = useState<OrgMember | null>(null);
  const [cancelling, setCancelling] = useState<OrgInvitation | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);

  if (error && !org) return <ApiErrorState error={error} thing="organization" onRetry={reload} />;
  if (!org || !data) {
    return (
      <PageShell title="Members" back={{ href: "/organizations", label: "Organizations" }}>
        <LoadingBlock label="Loading members…" />
      </PageShell>
    );
  }

  const roles = assignableRoles(role);
  const active = sortMembers(members);
  const pending = pendingInvitations(invitations.data ?? []);

  async function changeRole(member: OrgMember, next: AssignableRole) {
    if (next === member.role) return;
    setBusyId(member.id);
    setFeedback(null);
    try {
      const updated = await orgApi.changeRole(orgId, member.id, next);
      setData({ ...data!, members: members.map((m) => (m.id === member.id ? { ...m, role: updated.role as OrgRole } : m)) });
      setFeedback({ tone: "success", text: `${memberName(member)} is now ${ROLE_LABELS[next]}.` });
    } catch (err) {
      setFeedback({ tone: "error", text: orgErrorMessage(err) });
    } finally {
      setBusyId(null);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setBusyId(removing.id);
    setDialogError(null);
    try {
      await orgApi.removeMember(orgId, removing.id);
      setFeedback({ tone: "success", text: `${memberName(removing)} was removed.` });
      setRemoving(null);
      reload();
    } catch (err) {
      setDialogError(orgErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmCancelInvite() {
    if (!cancelling) return;
    setBusyId(cancelling.id);
    setDialogError(null);
    try {
      await orgApi.cancelInvitation(orgId, cancelling.id);
      setFeedback({ tone: "success", text: `The invitation for ${cancelling.email} was cancelled.` });
      setCancelling(null);
      invitations.reload();
    } catch (err) {
      setDialogError(orgErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <PageShell
      title="Members"
      description={org.name}
      back={{ href: `/organizations/${encodeURIComponent(org.id)}`, label: org.name }}
      actions={
        manager && org.is_active ? (
          <button type="button" className={btnPrimary} onClick={() => setInviting(true)}>
            Invite member
          </button>
        ) : undefined
      }
    >
      <OrgTabs org={org} />
      <InactiveNote org={org} />
      <div className="space-y-4">
        {feedback && <Notice tone={feedback.tone}>{feedback.text}</Notice>}

        <section aria-labelledby="members-heading">
          <h2 id="members-heading" className="mb-2 text-sm font-semibold text-white">
            {active.length} {active.length === 1 ? "member" : "members"}
          </h2>
          <ul className="space-y-2">
            {active.map((member) => (
              <MemberCard
                key={member.id}
                member={member}
                isMe={member.user_id === userId}
                manageable={member.user_id !== userId && canManageMember(role, member, org)}
                roles={roles}
                busy={busyId === member.id}
                onRole={(next) => changeRole(member, next)}
                onRemove={() => setRemoving(member)}
              />
            ))}
          </ul>
          {!manager && <p className="mt-3 text-xs text-muted">Only the owner and admins can invite or manage members.</p>}
        </section>

        {manager && (
          <Collapsible title="Pending invitations" meta={invitations.data ? `${pending.length}` : undefined}>
            {invitations.error && !invitations.data ? (
              <ApiErrorState error={invitations.error} thing="invitations" onRetry={invitations.reload} />
            ) : !invitations.data ? (
              <LoadingBlock label="Loading invitations…" />
            ) : pending.length === 0 ? (
              <p className="text-sm text-muted">No pending invitations.</p>
            ) : (
              <ul className="space-y-2">
                {pending.map((inv) => (
                  <li key={inv.id} className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 sm:flex-row sm:items-center">
                    <div className="min-w-0 flex-1">
                      <p className="break-all text-sm font-medium text-white">{inv.email}</p>
                      <p className="text-xs text-muted">
                        {ROLE_LABELS[inv.role]} · expires {new Date(inv.expires_at).toLocaleDateString()}
                      </p>
                    </div>
                    <button type="button" className={btnDanger} disabled={busyId === inv.id} onClick={() => setCancelling(inv)}>
                      Cancel invite
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted">Invite links are shown only when created. Lost one? Cancel it and invite again.</p>
          </Collapsible>
        )}
      </div>

      {manager && (
        <InviteSheet
          open={inviting}
          orgId={org.id}
          orgName={org.name}
          roles={roles}
          onClose={() => setInviting(false)}
          onInvited={() => invitations.reload()}
        />
      )}
      <ConfirmDialog
        open={!!removing}
        title={removing ? `Remove ${memberName(removing)}?` : "Remove member?"}
        message="They lose access to this organization and its clones right away. You can invite them again later."
        confirmLabel="Remove member"
        busyLabel="Removing…"
        busy={!!removing && busyId === removing.id}
        error={dialogError}
        onConfirm={confirmRemove}
        onCancel={() => {
          setRemoving(null);
          setDialogError(null);
        }}
      />
      <ConfirmDialog
        open={!!cancelling}
        title="Cancel this invitation?"
        message={cancelling ? `The link sent to ${cancelling.email} will stop working.` : ""}
        confirmLabel="Cancel invitation"
        busyLabel="Cancelling…"
        busy={!!cancelling && busyId === cancelling.id}
        error={dialogError}
        onConfirm={confirmCancelInvite}
        onCancel={() => {
          setCancelling(null);
          setDialogError(null);
        }}
      />
    </PageShell>
  );
}
