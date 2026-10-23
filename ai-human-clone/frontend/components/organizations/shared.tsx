"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useApiData } from "@/components/analytics/ui";
import { useAuth } from "@/components/AuthProvider";
import { orgApi } from "@/lib/orgApi";
import { ROLE_LABELS, displayName, initials, myRole } from "@/lib/orgRoles";
import type { Organization, OrgMember, OrgRole } from "@/types/organizations";

const ROLE_STYLES: Record<OrgRole, string> = {
  owner: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  admin: "border-accent/40 bg-accent/15 text-accent-soft",
  editor: "border-cyan/40 bg-cyan/10 text-cyan",
  viewer: "border-border bg-surface text-gray-300",
};

/** Role written out in words (color is only decoration). */
export function RoleBadge({ role }: { role: OrgRole }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${ROLE_STYLES[role]}`}>
      {ROLE_LABELS[role]}
    </span>
  );
}

export function MemberAvatar({ member }: { member: OrgMember }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent/20 text-sm font-semibold text-accent-soft"
    >
      {initials(member)}
    </span>
  );
}

export function memberName(member: OrgMember): string {
  return displayName(member);
}

/** The organization, its members, and the signed-in user's role in it. */
export function useOrg(orgId: string) {
  const { user } = useAuth();
  const result = useApiData(async () => {
    const [org, members] = await Promise.all([orgApi.get(orgId), orgApi.members(orgId)]);
    return { org, members };
  }, orgId);
  const role = result.data ? myRole(result.data.org, result.data.members, user?.id) : null;
  return { ...result, org: result.data?.org ?? null, members: result.data?.members ?? [], role, userId: user?.id };
}

/** Overview / Members / Settings tabs for one organization. */
export function OrgTabs({ org }: { org: Pick<Organization, "id"> }) {
  const pathname = usePathname();
  const base = `/organizations/${encodeURIComponent(org.id)}`;
  const tabs = [
    { href: base, label: "Overview" },
    { href: `${base}/members`, label: "Members" },
    { href: `${base}/settings`, label: "Settings" },
  ];
  return (
    <nav aria-label="Organization sections" className="mb-4 grid grid-cols-3 gap-1 rounded-xl border border-border bg-surface p-1">
      {tabs.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center justify-center rounded-lg text-sm ${
              active ? "bg-accent/25 font-medium text-white" : "text-muted hover:text-white"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function InactiveNote({ org }: { org: Organization }) {
  if (org.is_active) return null;
  return (
    <p role="status" className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      This organization is deactivated.
    </p>
  );
}
