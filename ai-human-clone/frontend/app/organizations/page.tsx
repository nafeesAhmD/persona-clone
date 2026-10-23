import type { Metadata } from "next";

import { OrganizationsList } from "@/components/organizations/OrganizationsList";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Organizations · Clone Me",
};

export default function OrganizationsPage() {
  return (
    <RequireAuth>
      <OrganizationsList />
    </RequireAuth>
  );
}
