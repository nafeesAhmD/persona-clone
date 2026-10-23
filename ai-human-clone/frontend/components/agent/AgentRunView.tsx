"use client";

import Link from "next/link";
import { useEffect, useId, useRef } from "react";

import { AgentStatusBadge, RiskBadge } from "@/components/agent/ui";
import type { AgentExecutionHandle } from "@/components/agent/useAgentExecution";
import { FormattedText } from "@/components/FormattedText";
import {
  formatDurationMs,
  formatInputPreview,
  hasMemoryProposal,
  isActiveStatus,
  isConfirmationPending,
  outcomeMessage,
  recentSteps,
  statusSentence,
  stepStatusIcon,
  stepStatusLabel,
  stepTypeLabel,
  toolTitle,
} from "@/lib/agentStatus";
import { cn } from "@/lib/utils";
import type { AgentExecution, AgentStep, AgentToolSetting } from "@/types/agent";

const btn =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-soft";
const btnPrimary = `${btn} bg-accent text-ink hover:bg-accent/90`;
const btnSecondary = `${btn} border border-border text-white hover:border-accent hover:bg-surface-raised`;
const btnDanger = `${btn} border border-rose-500/50 text-rose-200 hover:bg-rose-500/10`;

interface AgentRunViewProps {
  run: AgentExecutionHandle;
  /** Chat: newest steps only, no goal or result (the answer appears as a chat message). */
  compact?: boolean;
  tools?: AgentToolSetting[];
  /** Link to the full task view. */
  detailsHref?: string;
  /** Chat: give up on a task that can't be loaded. */
  onDismiss?: () => void;
}

export function AgentRunView({ run, compact = false, tools, detailsHref, onDismiss }: AgentRunViewProps) {
  const { execution, error } = run;

  if (!execution) {
    if (error) {
      const message = error instanceof Error ? error.message : "The task couldn't be loaded.";
      return (
        <div role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          <p>
            <span aria-hidden="true">⚠ </span>
            {message}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" onClick={run.reload} className={btnSecondary}>
              Try again
            </button>
            {onDismiss && (
              <button type="button" onClick={onDismiss} className={btnSecondary}>
                Dismiss
              </button>
            )}
          </div>
        </div>
      );
    }
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted">
        <Spinner />
        Starting the agent…
      </p>
    );
  }

  const active = isActiveStatus(execution.status);
  const outcome = outcomeMessage(execution);
  const sortedSteps = [...execution.steps].sort((a, b) => a.step_number - b.step_number);
  const { shown, hidden } = compact ? recentSteps(sortedSteps, 4) : { shown: sortedSteps, hidden: 0 };

  return (
    <div className={cn("min-w-0 space-y-3", compact && "rounded-2xl border border-cyan/30 bg-surface-raised/70 p-3")}>
      <div className="flex flex-wrap items-center gap-2">
        {compact && (
          <span className="text-xs font-semibold uppercase tracking-wide text-cyan">
            <span aria-hidden="true">🤖 </span>Agent
          </span>
        )}
        <AgentStatusBadge status={execution.status} />
        <span className="text-xs text-muted">
          {execution.steps.length === 1 ? "1 step" : `${execution.steps.length} steps`}
          {execution.tool_calls > 0 && ` · ${execution.tool_calls} tool ${execution.tool_calls === 1 ? "call" : "calls"}`}
        </span>
        {active && execution.status !== "waiting_confirmation" && <Spinner />}
      </div>
      {/* Status changes are announced once, politely. */}
      <p className="sr-only" aria-live="polite" role="status">
        {statusSentence(execution.status)}
      </p>

      {!compact && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Task</h2>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm text-gray-100">{execution.goal}</p>
        </div>
      )}

      {shown.length > 0 && (
        <div>
          {!compact && <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Steps</h2>}
          {hidden > 0 && <p className="mb-1 text-xs text-muted">+{hidden} earlier {hidden === 1 ? "step" : "steps"}</p>}
          <ol className={cn("space-y-2", compact && "space-y-1.5")} aria-label="Agent steps">
            {shown.map((step) => (
              <StepItem key={step.step_number} step={step} tools={tools} compact={compact} />
            ))}
          </ol>
        </div>
      )}
      {shown.length === 0 && active && <p className="text-sm text-muted">The agent is getting ready…</p>}

      {isConfirmationPending(execution) && execution.pending_action && <ConfirmationCard run={run} execution={execution} tools={tools} />}
      {hasMemoryProposal(execution) && <MemoryProposalCard run={run} execution={execution} />}

      {run.actionError && (
        <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          <span aria-hidden="true">⚠ </span>
          {run.actionError}
        </p>
      )}

      {!compact && execution.status === "completed" && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <h2 className="text-sm font-semibold text-emerald-200">
            <span aria-hidden="true">✓ </span>Result
          </h2>
          <div className="mt-2 break-words text-sm text-gray-100">
            {execution.result_summary ? <FormattedText text={execution.result_summary} /> : <span className="text-muted">No result text.</span>}
          </div>
        </div>
      )}

      {outcome && (
        <p
          role={execution.status === "cancelled" ? "status" : "alert"}
          className={cn(
            "rounded-xl border px-3 py-2 text-sm",
            execution.status === "cancelled" ? "border-border text-muted" : "border-rose-500/30 bg-rose-500/10 text-rose-200",
          )}
        >
          <span aria-hidden="true">{execution.status === "cancelled" ? "■ " : "⚠ "}</span>
          {outcome}
        </p>
      )}

      {(active || detailsHref) && (
        <div className="flex flex-wrap items-center gap-2">
          {active && (
            <button
              type="button"
              onClick={() => void run.cancel()}
              disabled={run.acting !== null}
              className={btnDanger}
            >
              {run.acting === "cancel" ? "Cancelling…" : "Cancel task"}
            </button>
          )}
          {detailsHref && (
            <Link href={detailsHref} className="inline-flex min-h-11 items-center px-1 text-sm text-accent-soft hover:underline">
              View all steps
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-cyan/30 border-t-cyan motion-reduce:animate-none"
    />
  );
}

function StepItem({ step, tools, compact }: { step: AgentStep; tools?: AgentToolSetting[]; compact: boolean }) {
  const tool = toolTitle(step.tool_name, tools);
  const duration = formatDurationMs(step.duration_ms);
  const failed = step.status === "failed" || step.status === "rejected";
  return (
    <li
      className={cn(
        "min-w-0 rounded-xl border border-border bg-surface/60 px-3 py-2",
        compact && "py-1.5",
        failed && "border-rose-500/30",
      )}
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
        <span className="font-semibold text-white">Step {step.step_number}</span>
        <span className="text-muted">{stepTypeLabel(step.step_type)}</span>
        {tool && <span className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-[11px] text-accent-soft">{tool}</span>}
        <span className={cn("inline-flex items-center gap-1", failed ? "text-rose-300" : step.status === "succeeded" ? "text-emerald-300" : "text-muted")}>
          <span aria-hidden="true">{stepStatusIcon(step.status)}</span>
          {stepStatusLabel(step.status)}
        </span>
        {duration && <span className="text-muted">· {duration}</span>}
      </p>
      {step.summary && (
        <p className={cn("mt-0.5 break-words text-sm text-gray-200", compact && "line-clamp-2 text-xs")}>{step.summary}</p>
      )}
    </li>
  );
}

/** "AI wants to perform this action." Focus moves here so keyboard and screen-reader users find it. */
function ConfirmationCard({ run, execution, tools }: { run: AgentExecutionHandle; execution: AgentExecution; tools?: AgentToolSetting[] }) {
  const action = execution.pending_action!;
  const preview = formatInputPreview(action.input_preview);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: false });
  }, [action.action_id]);

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-2xl border border-amber-400/50 bg-amber-400/10 p-4"
    >
      <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-sm font-semibold text-amber-100 outline-none">
        <span aria-hidden="true">✋ </span>AI wants to perform this action.
      </h3>
      <dl className="mt-3 space-y-2 text-sm">
        <div>
          <dt className="text-xs text-muted">Action</dt>
          <dd className="break-words font-medium text-white">{action.title}</dd>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <dt className="sr-only">Tool</dt>
          <dd className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-accent-soft">{toolTitle(action.tool, tools)}</dd>
          <dt className="sr-only">Risk</dt>
          <dd>
            <RiskBadge risk={action.risk} />
          </dd>
        </div>
        {action.reason && (
          <div>
            <dt className="text-xs text-muted">Why</dt>
            <dd className="break-words text-gray-100">{action.reason}</dd>
          </div>
        )}
        {preview && (
          <div>
            <dt className="text-xs text-muted">Details</dt>
            <dd>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-surface p-2 font-mono text-xs text-gray-200">
                {preview}
              </pre>
            </dd>
          </div>
        )}
      </dl>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:flex">
        <button
          type="button"
          onClick={() => void run.reject(action.action_id)}
          disabled={run.acting !== null}
          className={btnSecondary}
        >
          {run.acting === "reject" ? "Rejecting…" : "Reject"}
        </button>
        <button
          type="button"
          onClick={() => void run.confirm(action.action_id)}
          disabled={run.acting !== null}
          className={btnPrimary}
        >
          {run.acting === "confirm" ? "Confirming…" : "Confirm"}
        </button>
      </div>
    </section>
  );
}

function MemoryProposalCard({ run, execution }: { run: AgentExecutionHandle; execution: AgentExecution }) {
  const proposal = execution.memory_proposal!;
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="rounded-2xl border border-accent/40 bg-accent/10 p-4">
      <h3 id={headingId} className="text-sm font-semibold text-accent-soft">
        <span aria-hidden="true">🧠 </span>Memory suggestion
      </h3>
      <p className="mt-2 break-words text-sm text-gray-100">
        I learned that <q className="font-medium text-white">{proposal.content}</q>. Would you like me to save this?
      </p>
      {proposal.memory_type && <p className="mt-1 text-xs text-muted">Type: {proposal.memory_type.replace(/_/g, " ")}</p>}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:flex">
        <button
          type="button"
          onClick={() => void run.answerMemory(proposal.proposal_id, false)}
          disabled={run.acting !== null}
          className={btnSecondary}
        >
          {run.acting === "discard_memory" ? "Skipping…" : "Don't save"}
        </button>
        <button
          type="button"
          onClick={() => void run.answerMemory(proposal.proposal_id, true)}
          disabled={run.acting !== null}
          className={btnPrimary}
        >
          {run.acting === "save_memory" ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}
