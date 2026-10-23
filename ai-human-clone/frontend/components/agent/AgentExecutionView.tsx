"use client";

import Link from "next/link";

import { AgentRunView } from "@/components/agent/AgentRunView";
import { useAgentExecution } from "@/components/agent/useAgentExecution";
import { Card, LoadingBlock, PageShell, btnSecondary, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { agentApi } from "@/lib/agentApi";
import { formatDurationMs } from "@/lib/agentStatus";

function duration(start: string | null, end: string | null): string {
  if (!start || !end) return "";
  return formatDurationMs(new Date(end).getTime() - new Date(start).getTime());
}

/** One agent task: live status, visible steps, approvals, memory suggestion and result. */
export function AgentExecutionView({ cloneId, executionId }: { cloneId: string; executionId: string }) {
  const run = useAgentExecution(executionId);
  // Tool titles for the steps (optional: the page works without them).
  const agent = useApiData(() => agentApi.get(cloneId), cloneId);
  const encodedId = encodeURIComponent(cloneId);
  const back = { href: `/clone/${encodedId}/agent`, label: "Back to AI Agent" };
  const execution = run.execution;

  if (!execution && run.error) {
    return <ApiErrorState error={run.error} thing="agent task" onRetry={run.reload} />;
  }

  const startedAt = execution ? execution.started_at ?? execution.created_at : null;
  const took = execution ? duration(startedAt, execution.completed_at) : "";

  return (
    <PageShell title="Agent task" back={back} busy={run.active}>
      {!execution ? (
        <LoadingBlock label="Loading the task…" />
      ) : (
        <div className="space-y-4">
          <Card>
            <AgentRunView run={run} tools={agent.data?.tools} />
          </Card>
          <Card>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <Fact label="Started" value={startedAt ? new Date(startedAt).toLocaleString() : "Not yet"} />
              <Fact label="Took" value={took || "—"} />
              <Fact label="Steps" value={String(execution.steps.length)} />
              <Fact label="Tool calls" value={String(execution.tool_calls)} />
            </dl>
          </Card>
          {execution.conversation_id && execution.status === "completed" && (
            <Link href={`/clone/${encodedId}?c=${encodeURIComponent(execution.conversation_id)}`} className={btnSecondary}>
              Open the conversation
            </Link>
          )}
        </div>
      )}
    </PageShell>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="break-words text-white">{value}</dd>
    </div>
  );
}
