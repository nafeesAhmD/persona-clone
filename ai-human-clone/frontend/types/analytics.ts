/** Periods the analytics API accepts. */
export type AnalyticsRange = "today" | "yesterday" | "7d" | "30d" | "90d";

/** GET /api/clones/{id}/analytics/overview. Counts only, never content. */
export interface AnalyticsOverview {
  total_conversations: number;
  total_messages: number;
  total_unique_sessions: number;
  /** Visitors: public chat sessions started in the period. */
  total_public_sessions: number;
  /** Knowledge: totals right now (not per period). */
  total_documents: number;
  total_memories: number;
  total_voice_requests: number;
  total_avatar_requests: number;
  successful_requests: number;
  failed_requests: number;
  /** Milliseconds, or null when nothing was measured. */
  average_response_time: number | null;
  total_usage_events: number;
}

export interface DailyActivity {
  /** YYYY-MM-DD (UTC). */
  date: string;
  conversations: number;
  messages: number;
  sessions: number;
  errors: number;
}

/** GET /api/clones/{id}/analytics/activity. */
export interface CloneActivity {
  clone_id: string;
  range: AnalyticsRange;
  start: string;
  end: string;
  days: DailyActivity[];
}

export type ActivityMetric = "messages" | "conversations" | "sessions" | "errors";
