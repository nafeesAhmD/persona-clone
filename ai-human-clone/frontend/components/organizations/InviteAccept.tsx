"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, LoadingBlock, PageShell, btnPrimary, btnSecondary } from "@/components/analytics/ui";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import { orgApi } from "@/lib/orgApi";
import { ROLE_LABELS, orgErrorMessage } from "@/lib/orgRoles";
import type { InvitationAccepted } from "@/types/organizations";

type Outcome =
  | { kind: "accepted"; result: InvitationAccepted }
  | { kind: "declined" }
  | { kind: "wrong_account" }
  | { kind: "invalid" }
  | { kind: "already_member" }
  | { kind: "error"; message: string };

function outcomeFor(error: unknown): Outcome {
  const code = error instanceof Error ? error.message.trim() : "";
  if (code === "invitation_for_another_email" || (error instanceof ApiError && error.status === 403)) return { kind: "wrong_account" };
  if (code === "invalid_or_expired") return { kind: "invalid" };
  if (code === "already_member") return { kind: "already_member" };
  if (error instanceof ApiError && (error.kind === "rate_limit" || error.status === 429)) {
    return { kind: "error", message: "Too many attempts. Please wait a minute and try again." };
  }
  if (error instanceof ApiError && (error.kind === "offline" || error.kind === "timeout" || error.kind === "network")) {
    return { kind: "error", message: error.message || "You seem to be offline. Check your connection and try again." };
  }
  return { kind: "error", message: orgErrorMessage(error, "Something went wrong. Please try again.") };
}

/** /invite/{token}: sign in (and come back), then accept or decline. */
export function InviteAccept({ token }: { token: string }) {
  const { status, user, logout } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const here = `/invite/${encodeURIComponent(token)}`;
  const loginHref = `/login?next=${encodeURIComponent(here)}`;

  async function act(kind: "accept" | "decline") {
    setBusy(kind);
    try {
      if (kind === "accept") setOutcome({ kind: "accepted", result: await orgApi.acceptInvitation(token) });
      else {
        await orgApi.declineInvitation(token);
        setOutcome({ kind: "declined" });
      }
    } catch (error) {
      setOutcome(outcomeFor(error));
    } finally {
      setBusy(null);
    }
  }

  async function switchAccount() {
    await logout();
    router.push(loginHref);
  }

  let body: React.ReactNode;
  if (status === "loading") {
    body = <LoadingBlock label="Checking your session…" />;
  } else if (status === "anonymous") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white">Sign in to answer this invitation</h2>
        <p className="mt-2 text-sm text-gray-200">
          Use the account with the email address the invitation was sent to. You&apos;ll come straight back here.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Link href={loginHref} className={btnPrimary}>
            Log in
          </Link>
          <Link href={`/register?next=${encodeURIComponent(here)}`} className={btnSecondary}>
            Create an account
          </Link>
        </div>
        <p className="mt-3 text-xs text-muted">New here? After creating your account, open this invite link again to accept.</p>
      </Card>
    );
  } else if (outcome?.kind === "accepted") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white" role="status">
          You&apos;ve joined the organization
        </h2>
        <p className="mt-2 text-sm text-gray-200">Your role: {ROLE_LABELS[outcome.result.role] ?? outcome.result.role}.</p>
        <Link href={`/organizations/${encodeURIComponent(outcome.result.organization_id)}`} className={`${btnPrimary} mt-4 w-full sm:w-auto`}>
          Open organization
        </Link>
      </Card>
    );
  } else if (outcome?.kind === "declined") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white" role="status">
          Invitation declined
        </h2>
        <p className="mt-2 text-sm text-gray-200">We&apos;ve let the organization know. Nothing else changes.</p>
        <Link href="/dashboard" className={`${btnSecondary} mt-4 w-full sm:w-auto`}>
          Go to dashboard
        </Link>
      </Card>
    );
  } else if (outcome?.kind === "wrong_account") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white" role="alert">
          This invitation is for a different account
        </h2>
        <p className="mt-2 text-sm text-gray-200">
          You&apos;re signed in as <span className="break-all font-medium text-white">{user?.email}</span>, but the invitation was sent to
          another email address. Sign in with that address to accept it.
        </p>
        <button type="button" className={`${btnPrimary} mt-4 w-full sm:w-auto`} onClick={switchAccount}>
          Switch account
        </button>
      </Card>
    );
  } else if (outcome?.kind === "invalid") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white" role="alert">
          This invitation can&apos;t be used
        </h2>
        <p className="mt-2 text-sm text-gray-200">
          It has expired, was cancelled, or was already used. Ask the person who invited you for a new link.
        </p>
        <Link href="/organizations" className={`${btnSecondary} mt-4 w-full sm:w-auto`}>
          Your organizations
        </Link>
      </Card>
    );
  } else if (outcome?.kind === "already_member") {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white" role="status">
          You&apos;re already a member
        </h2>
        <Link href="/organizations" className={`${btnPrimary} mt-4 w-full sm:w-auto`}>
          Your organizations
        </Link>
      </Card>
    );
  } else {
    body = (
      <Card>
        <h2 className="text-lg font-semibold text-white">You&apos;ve been invited to join an organization</h2>
        <p className="mt-2 text-sm text-gray-200">
          Signed in as <span className="break-all font-medium text-white">{user?.email}</span>. Members can work on the
          organization&apos;s clones with the role they were given.
        </p>
        {outcome?.kind === "error" && (
          <p role="alert" className="mt-3 text-sm text-rose-300">
            {outcome.message}
          </p>
        )}
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button type="button" className={btnPrimary} disabled={busy !== null} onClick={() => act("accept")}>
            {busy === "accept" ? "Joining…" : "Accept invitation"}
          </button>
          <button type="button" className={btnSecondary} disabled={busy !== null} onClick={() => act("decline")}>
            {busy === "decline" ? "Declining…" : "Decline"}
          </button>
        </div>
      </Card>
    );
  }

  return (
    <PageShell title="Organization invitation">
      <div className="mx-auto max-w-lg">{body}</div>
    </PageShell>
  );
}
