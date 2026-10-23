import { apiFetch } from "@/lib/api";
import type {
  AgentAnalytics,
  AgentAnalyticsRange,
  AgentExecution,
  AgentExecutionPage,
  AgentProfile,
  AgentProfileUpdate,
  AgentRunRequest,
  AgentRunResponse,
  AgentToolSetting,
  AgentToolUpdate,
} from "@/types/agent";

const clonePath = (cloneId: string) => `/api/clones/${encodeURIComponent(cloneId)}`;
const executionPath = (executionId: string) => `/api/agent/executions/${encodeURIComponent(executionId)}`;

/** The controlled AI agent (Phase 16). The API checks access on every call. */
export const agentApi = {
  get(cloneId: string): Promise<AgentProfile> {
    return apiFetch<AgentProfile>(`${clonePath(cloneId)}/agent`, { cache: "no-store" });
  },

  update(cloneId: string, update: AgentProfileUpdate): Promise<AgentProfile> {
    return apiFetch<AgentProfile>(`${clonePath(cloneId)}/agent`, { method: "PATCH", body: JSON.stringify(update) });
  },

  setTool(cloneId: string, toolName: string, update: AgentToolUpdate): Promise<AgentToolSetting> {
    return apiFetch<AgentToolSetting>(`${clonePath(cloneId)}/agent/tools/${encodeURIComponent(toolName)}`, {
      method: "PUT",
      body: JSON.stringify(update),
    });
  },

  /** Starts a task; the answer is 202 with the execution to poll. */
  run(cloneId: string, request: AgentRunRequest): Promise<AgentRunResponse> {
    return apiFetch<AgentRunResponse>(`${clonePath(cloneId)}/agent/run`, { method: "POST", body: JSON.stringify(request) });
  },

  executions(cloneId: string, page = 1, limit = 20): Promise<AgentExecutionPage> {
    return apiFetch<AgentExecutionPage>(`${clonePath(cloneId)}/agent/executions?page=${page}&limit=${limit}`, {
      cache: "no-store",
    });
  },

  execution(executionId: string): Promise<AgentExecution> {
    return apiFetch<AgentExecution>(executionPath(executionId), { cache: "no-store" });
  },

  cancel(executionId: string): Promise<AgentExecution> {
    return apiFetch<AgentExecution>(`${executionPath(executionId)}/cancel`, { method: "POST" });
  },

  confirm(executionId: string, actionId: string): Promise<AgentExecution> {
    return apiFetch<AgentExecution>(`${executionPath(executionId)}/confirm`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId }),
    });
  },

  reject(executionId: string, actionId: string): Promise<AgentExecution> {
    return apiFetch<AgentExecution>(`${executionPath(executionId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId }),
    });
  },

  answerMemoryProposal(executionId: string, proposalId: string, save: boolean): Promise<AgentExecution> {
    return apiFetch<AgentExecution>(`${executionPath(executionId)}/memory-proposal`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, save }),
    });
  },

  analytics(cloneId: string, range: AgentAnalyticsRange): Promise<AgentAnalytics> {
    return apiFetch<AgentAnalytics>(`${clonePath(cloneId)}/analytics/agent?range=${range}`, { cache: "no-store" });
  },
};
