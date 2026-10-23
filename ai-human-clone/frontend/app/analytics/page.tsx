import type { Metadata } from "next";

import { AnalyticsHub } from "@/components/analytics/AnalyticsHub";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Analytics · Clone Me",
};

export default function AnalyticsPage() {
  return (
    <RequireAuth>
      <AnalyticsHub />
    </RequireAuth>
  );
}
