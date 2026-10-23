import { apiFetch } from "@/lib/api";
import type { AnalyticsOverview, AnalyticsRange, CloneActivity } from "@/types/analytics";

const base = (cloneId: string) => `/api/clones/${encodeURIComponent(cloneId)}/analytics`;

/** Owner-only clone analytics. Counts only; no conversation content. */
export const analyticsApi = {
  overview(cloneId: string, range: AnalyticsRange): Promise<AnalyticsOverview> {
    return apiFetch<AnalyticsOverview>(`${base(cloneId)}/overview?range=${range}`, { cache: "no-store" });
  },
  activity(cloneId: string, range: AnalyticsRange): Promise<CloneActivity> {
    return apiFetch<CloneActivity>(`${base(cloneId)}/activity?range=${range}`, { cache: "no-store" });
  },
};
