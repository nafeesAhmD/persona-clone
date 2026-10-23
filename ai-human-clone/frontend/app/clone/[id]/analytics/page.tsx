import type { Metadata } from "next";

import { CloneAnalyticsView } from "@/components/analytics/CloneAnalyticsView";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = {
  title: "Clone Analytics · Clone Me",
};

export default async function CloneAnalyticsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <CloneAnalyticsView cloneId={id} />
    </RequireAuth>
  );
}
