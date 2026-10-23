// Pure helpers for the AI agent screens (no React, no DOM): tested in tests/agent.test.ts.
import type {
  AgentExecution,
  AgentExecutionStatus,
  AgentProfile,
  AgentRisk,
  AgentStepStatus,
  AgentStepType,
  AgentToolSetting,
  AgentToolUsage,
} from "@/types/agent";

/** How often a running task is checked. */
export const POLL_INTERVAL_MS = 1500;

/** Same limit as the API (goal: 1..4000 characters). */
export const GOAL_MAX_LENGTH = 4000;

/** Lower bounds of the server's settings (model check constraints). */
export const MIN_STEPS = 1;
export const MIN_EXECUTION_SECONDS = 5;

const POLLING: ReadonlySet<string> = new Set(["queued", "planning", "running"]);
const FINAL: ReadonlySet<string> = new Set(["completed", "failed", "cancelled", "timeout"]);

/** Queued / planning / running: keep checking. Final states and waiting_confirmation: stop. */
export function shouldPoll(status: string | null | undefined): boolean {
  return typeof status === "string" && POLLING.has(status);
}

export function isFinalStatus(status: string | null | undefined): boolean {
  return typeof status === "string" && FINAL.has(status);
}

/** Not finished yet (includes waiting for the user's OK): a run is "in progress". */
export function isActiveStatus(status: string | null | undefined): boolean {
  return typeof status === "string" && !FINAL.has(status);
}

/** The task is paused until the user confirms or rejects an action. */
export function isConfirmationPending(
  execution: Pick<AgentExecution, "status" | "requires_confirmation" | "pending_action"> | null | undefined,
): boolean {
  if (!execution || isFinalStatus(execution.status)) return false;
  return Boolean(execution.pending_action) && (execution.status === "waiting_confirmation" || execution.requires_confirmation);
}

/** A suggested memory waiting for Save / Don't save. */
export function hasMemoryProposal(execution: Pick<AgentExecution, "memory_proposal"> | null | undefined): boolean {
  return Boolean(execution?.memory_proposal?.proposal_id);
}

const STATUS_LABELS: Record<AgentExecutionStatus, string> = {
  queued: "Queued",
  planning: "Planning",
  running: "Running",
  waiting_confirmation: "Waiting for your approval",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  timeout: "Timed out",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as AgentExecutionStatus] ?? status.replace(/_/g, " ");
}

export type StatusTone = "active" | "waiting" | "success" | "error" | "neutral";

export function statusTone(status: string): StatusTone {
  if (shouldPoll(status)) return "active";
  if (status === "waiting_confirmation") return "waiting";
  if (status === "completed") return "success";
  if (status === "failed" || status === "timeout") return "error";
  return "neutral";
}

/** A text symbol next to every status, so it never relies on color alone. */
export function statusIcon(status: string): string {
  switch (statusTone(status)) {
    case "active":
      return "⏳";
    case "waiting":
      return "✋";
    case "success":
      return "✓";
    case "error":
      return "⚠";
    default:
      return "■";
  }
}

/** A sentence for screen readers and the status line. */
export function statusSentence(status: string): string {
  switch (status) {
    case "queued":
      return "The task is queued and will start shortly.";
    case "planning":
      return "The agent is planning the next step.";
    case "running":
      return "The agent is working on the task.";
    case "waiting_confirmation":
      return "The agent is waiting for your approval.";
    case "completed":
      return "The task is complete.";
    case "failed":
      return "The task failed.";
    case "cancelled":
      return "The task was cancelled.";
    case "timeout":
      return "The task ran out of time.";
    default:
      return statusLabel(status);
  }
}

const RISKS: AgentRisk[] = ["low", "medium", "high", "critical"];

/** Unknown values are treated as "medium" so they're never shown as harmless. */
export function normalizeRisk(risk: string | null | undefined): AgentRisk {
  return RISKS.includes(risk as AgentRisk) ? (risk as AgentRisk) : "medium";
}

export function riskLabel(risk: string | null | undefined): string {
  const value = normalizeRisk(risk);
  return `${value[0].toUpperCase()}${value.slice(1)} risk`;
}

export function riskIcon(risk: string | null | undefined): string {
  const value = normalizeRisk(risk);
  if (value === "low") return "●";
  if (value === "medium") return "▲";
  return "⛔";
}

const STEP_TYPE_LABELS: Record<AgentStepType, string> = {
  plan: "Planning",
  tool: "Tool",
  confirmation: "Approval",
  memory_proposal: "Memory suggestion",
  final: "Final answer",
  error: "Error",
};

export function stepTypeLabel(type: string): string {
  return STEP_TYPE_LABELS[type as AgentStepType] ?? type.replace(/_/g, " ");
}

const STEP_STATUS: Record<AgentStepStatus, { label: string; icon: string }> = {
  running: { label: "Running", icon: "⏳" },
  succeeded: { label: "Done", icon: "✓" },
  failed: { label: "Failed", icon: "⚠" },
  skipped: { label: "Skipped", icon: "↷" },
  waiting: { label: "Waiting", icon: "✋" },
  rejected: { label: "Rejected", icon: "✕" },
};

export function stepStatusLabel(status: string): string {
  return STEP_STATUS[status as AgentStepStatus]?.label ?? status;
}

export function stepStatusIcon(status: string): string {
  return STEP_STATUS[status as AgentStepStatus]?.icon ?? "•";
}

/** "Knowledge search" for "knowledge_search"; uses the tool list's title when known. */
export function toolTitle(name: string | null | undefined, tools?: Pick<AgentToolSetting, "name" | "title">[]): string {
  if (!name) return "";
  const known = tools?.find((tool) => tool.name === name)?.title;
  if (known) return known;
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : name;
}

/** "120 ms", "2.4 s", "1 min 5 s", or "" when unknown. */
export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

/** Failure rate in whole percent, from the counts (the API's failure_rate may be 0..1 or 0..100). */
export function failureRatePercent(usage: Pick<AgentToolUsage, "calls" | "failures" | "failure_rate">): number {
  if (usage.calls > 0) return Math.round((Math.min(usage.failures, usage.calls) / usage.calls) * 100);
  const rate = Number(usage.failure_rate);
  if (!Number.isFinite(rate) || rate <= 0) return 0;
  return Math.round(rate <= 1 ? rate * 100 : Math.min(rate, 100));
}

/** Most-used tools first. */
export function sortToolUsage<T extends Pick<AgentToolUsage, "calls" | "tool">>(tools: T[]): T[] {
  return [...tools].sort((a, b) => b.calls - a.calls || a.tool.localeCompare(b.tool));
}

/** Whole number within [min, max]; NaN falls back to min. */
export function clampInt(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  const upper = Math.max(min, max);
  return Math.min(upper, Math.max(min, Math.round(value)));
}

/** A problem with the task text, or null when it can be sent. */
export function validateGoal(goal: string): string | null {
  const text = goal.trim();
  if (!text) return "Describe the task for the agent.";
  if (text.length > GOAL_MAX_LENGTH) return `The task is too long (maximum ${GOAL_MAX_LENGTH} characters).`;
  return null;
}

export type AgentAvailability = "platform_off" | "agent_off" | "no_access" | "ready";

/** Whether this viewer can run the agent now, and if not, why. */
export function agentAvailability(
  profile: Pick<AgentProfile, "platform_enabled" | "enabled" | "can_run"> | null | undefined,
): AgentAvailability {
  if (!profile) return "no_access";
  if (!profile.platform_enabled) return "platform_off";
  if (!profile.enabled) return "agent_off";
  if (!profile.can_run) return "no_access";
  return "ready";
}

export function availabilityMessage(availability: AgentAvailability, canConfigure: boolean): string {
  switch (availability) {
    case "platform_off":
      return "The AI agent is turned off on this server. An administrator can turn it on (AGENT_ENABLED).";
    case "agent_off":
      return canConfigure
        ? "The AI agent is off for this clone. Turn it on below to run tasks."
        : "The AI agent is turned off for this clone.";
    case "no_access":
      return "You don't have permission to run this clone's agent.";
    default:
      return "The AI agent is on and ready.";
  }
}

/** The chat shows the Normal Chat / Agent Mode switch only when the agent can run. */
export function canUseAgentMode(profile: Pick<AgentProfile, "platform_enabled" | "enabled" | "can_run"> | null | undefined): boolean {
  return agentAvailability(profile) === "ready";
}

/** Why a tool switch is disabled, or null when it can be changed. */
export function toolLockReason(tool: Pick<AgentToolSetting, "available" | "reason_unavailable">, canConfigure: boolean): string | null {
  if (!tool.available) return tool.reason_unavailable || "Not available on this server.";
  if (!canConfigure) return "Only the clone's owner or an organization admin can change tools.";
  return null;
}

/** A short line for a finished task that didn't complete. */
export function outcomeMessage(execution: Pick<AgentExecution, "status" | "error">): string | null {
  switch (execution.status) {
    case "failed":
      return execution.error || "The agent couldn't finish this task.";
    case "timeout":
      return execution.error || "The agent ran out of time before finishing.";
    case "cancelled":
      return "The task was cancelled.";
    default:
      return null;
  }
}

/** The action's input preview as display text (the API may send text or a small object). */
export function formatInputPreview(preview: unknown, maxLength = 2000): string {
  if (preview === null || preview === undefined) return "";
  let text: string;
  if (typeof preview === "string") text = preview;
  else {
    try {
      text = JSON.stringify(preview, null, 2) ?? "";
    } catch {
      text = String(preview);
    }
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text;
}

/** Number of pages for a paginated list (at least 1). */
export function pageCount(total: number, limit: number): number {
  if (!Number.isFinite(total) || !Number.isFinite(limit) || limit <= 0 || total <= 0) return 1;
  return Math.ceil(total / limit);
}

/** The newest few steps for the compact list in the chat. */
export function recentSteps<T extends { step_number: number }>(steps: T[], max = 4): { shown: T[]; hidden: number } {
  const sorted = [...steps].sort((a, b) => a.step_number - b.step_number);
  const shown = sorted.slice(-Math.max(1, max));
  return { shown, hidden: sorted.length - shown.length };
}
