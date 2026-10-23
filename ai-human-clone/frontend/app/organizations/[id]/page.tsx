import type { Metadata } from "next";

import { OrgOverview } from "@/components/organizations/OrgOverview";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Organization · Clone Me",
};

export default async function OrganizationOverviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <OrgOverview orgId={id} />
    </RequireAuth>
  );
}
