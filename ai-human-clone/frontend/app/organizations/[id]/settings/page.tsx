import type { Metadata } from "next";

import { OrgSettings } from "@/components/organizations/OrgSettings";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Organization Settings · Clone Me",
};

export default async function OrganizationSettingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <OrgSettings orgId={id} />
    </RequireAuth>
  );
}
