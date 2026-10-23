/** Phase 16: the controlled AI agent (docs/phase16/contract.md). */

export type AgentRisk = "low" | "medium" | "high" | "critical";

export type AgentExecutionStatus =
  | "queued"
  | "planning"
  | "running"
  | "waiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled"
  | "timeout";

export type AgentStepType = "plan" | "tool" | "confirmation" | "memory_proposal" | "final" | "error";

export type AgentStepStatus = "running" | "succeeded" | "failed" | "skipped" | "waiting" | "rejected";

export type AgentSource = "app" | "api" | "public";

/** One tool as configured for a clone's agent. */
export interface AgentToolSetting {
  name: string;
  title: string;
  description: string;
  risk: AgentRisk;
  permission_scope: string;
  enabled: boolean;
  require_confirmation: boolean;
  /** False when the server doesn't offer the tool (e.g. web search turned off). */
  available: boolean;
  reason_unavailable: string | null;
}

export interface AgentLimits {
  max_steps: number;
  max_execution_time_seconds: number;
  max_tool_calls: number;
}

/** GET /api/clones/{id}/agent */
export interface AgentProfile {
  id: string;
  clone_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  max_steps: number;
  max_execution_time_seconds: number;
  require_confirmation_for_actions: boolean;
  allow_viewer_use: boolean;
  public_agent_enabled: boolean;
  /** AGENT_ENABLED on the server. */
  platform_enabled: boolean;
  can_configure: boolean;
  can_run: boolean;
  limits: AgentLimits;
  tools: AgentToolSetting[];
}

export interface AgentProfileUpdate {
  enabled?: boolean;
  name?: string;
  description?: string | null;
  max_steps?: number;
  max_execution_time_seconds?: number;
  require_confirmation_for_actions?: boolean;
  allow_viewer_use?: boolean;
  public_agent_enabled?: boolean;
}

export interface AgentToolUpdate {
  enabled: boolean;
  require_confirmation: boolean;
}

export interface AgentRunRequest {
  goal: string;
  conversation_id?: string | null;
  input_mode?: "text" | "voice";
}

export interface AgentRunResponse {
  execution_id: string;
  status: AgentExecutionStatus;
}

export interface AgentExecutionSummary {
  id: string;
  status: AgentExecutionStatus;
  /** Shortened to 200 characters. */
  goal: string;
  total_steps: number;
  created_at: string | null;
  completed_at: string | null;
  source: AgentSource;
}

export interface AgentExecutionPage {
  items: AgentExecutionSummary[];
  page: number;
  limit: number;
  total: number;
}

/** The action waiting for the user's OK. */
export interface AgentPendingAction {
  action_id: string;
  tool: string;
  title: string;
  reason: string | null;
  risk: AgentRisk;
  /** A short, safe preview: text or a small object (see formatInputPreview). */
  input_preview: string | Record<string, unknown> | null;
}

export interface AgentMemoryProposal {
  proposal_id: string;
  content: string;
  memory_type: string;
}

/** A visible step: a short summary only (never hidden reasoning). */
export interface AgentStep {
  step_number: number;
  step_type: AgentStepType;
  tool_name: string | null;
  status: AgentStepStatus;
  summary: string | null;
  duration_ms: number | null;
  created_at: string | null;
}

/** GET /api/agent/executions/{id} */
export interface AgentExecution {
  id: string;
  clone_id: string;
  status: AgentExecutionStatus;
  goal: string;
  current_step: number;
  total_steps: number;
  tool_calls: number;
  result_summary: string | null;
  error: string | null;
  requires_confirmation: boolean;
  pending_action: AgentPendingAction | null;
  memory_proposal: AgentMemoryProposal | null;
  steps: AgentStep[];
  conversation_id: string | null;
  final_message_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export type AgentAnalyticsRange = "7d" | "30d" | "90d";

export interface AgentToolUsage {
  tool: string;
  calls: number;
  failures: number;
  /** 0..1 or a percentage; see lib/agentStatus.ts formatFailureRate. */
  failure_rate: number;
}

/** GET /api/clones/{id}/analytics/agent */
export interface AgentAnalytics {
  range: AgentAnalyticsRange;
  executions: number;
  completed: number;
  failed: number;
  cancelled: number;
  timeout: number;
  avg_duration_ms: number | null;
  avg_steps: number | null;
  tools: AgentToolUsage[];
}
