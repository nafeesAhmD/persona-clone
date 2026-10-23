import type { Metadata } from "next";

import { Dashboard } from "@/components/Dashboard";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Dashboard · Clone Me",
};

export default function DashboardPage() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
