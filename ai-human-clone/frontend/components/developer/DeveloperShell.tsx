"use client";

import { usePathname } from "next/navigation";

import { SectionNav } from "@/components/mobile/SectionNav";
import { RequireAuth } from "@/components/RequireAuth";

const NAV = [
  { href: "/developer", label: "Overview" },
  { href: "/developer/keys", label: "API Keys" },
  { href: "/developer/webhooks", label: "Webhooks" },
  { href: "/developer/usage", label: "Usage" },
  { href: "/developer/docs", label: "Docs" },
];

/** Developer area: login check and the sidebar. Every /api/developer call is authorized by the server. */
export function DeveloperShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/developer";
  return (
    <RequireAuth>
      <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-6 sm:px-6 lg:flex-row lg:gap-6">
        <SectionNav label="Developer" heading="Developer" headingClass="text-cyan" items={NAV} pathname={pathname} />
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </RequireAuth>
  );
}
