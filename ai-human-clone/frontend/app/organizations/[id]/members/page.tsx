import type { Metadata } from "next";

import { OrgMembers } from "@/components/organizations/OrgMembers";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Members · Clone Me",
};

export default async function OrganizationMembersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <OrgMembers orgId={id} />
    </RequireAuth>
  );
}
