"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/AuthProvider";
import { RequireAuth } from "@/components/RequireAuth";
import { SectionNav } from "@/components/mobile/SectionNav";
import { StatusMessage } from "@/components/StatusMessage";

const NAV = [
  { href: "/admin/dashboard", label: "Dashboard" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/clones", label: "Clones" },
  { href: "/admin/content", label: "Content" },
  { href: "/admin/marketplace", label: "Marketplace" },
  { href: "/admin/security", label: "Security" },
  { href: "/admin/usage", label: "Usage" },
  { href: "/admin/developer", label: "Developer" },
  { href: "/admin/system", label: "System" },
  { href: "/admin/system/errors", label: "Errors" },
  { href: "/admin/settings", label: "Settings" },
];

/**
 * Admin layout: login check, admin check and the sidebar. The checks here only
 * decide what to show; every /api/admin request is authorized by the server.
 */
export function AdminShell({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AdminOnly>{children}</AdminOnly>
    </RequireAuth>
  );
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname() ?? "/admin";

  if (!user?.is_admin) {
    return (
      <StatusMessage title="Administrator access required" body="This area is only for platform administrators.">
        <Link href="/dashboard" className="text-accent-soft hover:underline">
          Back to dashboard
        </Link>
      </StatusMessage>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-6 sm:px-6 lg:flex-row lg:gap-6">
      <SectionNav label="Admin" heading="Admin" headingClass="text-amber-300" items={NAV} pathname={pathname} />
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
