"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { agentApi } from "@/lib/agentApi";
import { POLL_INTERVAL_MS, isActiveStatus, isFinalStatus, shouldPoll } from "@/lib/agentStatus";
import { beginBusy } from "@/lib/busy";
import type { AgentExecution } from "@/types/agent";

export type AgentAction = "cancel" | "confirm" | "reject" | "save_memory" | "discard_memory";

/** Errors that won't fix themselves by asking again. */
function isFatal(error: unknown): boolean {
  const kind = (error as { kind?: unknown } | null)?.kind;
  return kind === "auth" || kind === "forbidden" || kind === "not_found" || kind === "invalid";
}

const MAX_BACKOFF_MS = 10_000;

/**
 * Follows one agent task: checks it every ~1.5 s while it is queued / planning /
 * running, and stops on a final state or while it waits for the user's approval
 * (an approval or rejection starts it again). While the task is unfinished the app
 * is marked busy, so a PWA update never reloads the page mid-run.
 *
 * `onFinal` is called once per task when it reaches a final state.
 */
export function useAgentExecution(executionId: string | null, onFinal?: (execution: AgentExecution) => void) {
  const [state, setState] = useState<{ id: string | null; execution: AgentExecution | null; error: unknown }>({
    id: null,
    execution: null,
    error: null,
  });
  const [version, setVersion] = useState(0);
  const [acting, setActing] = useState<AgentAction | null>(null);
  const [actionError, setActionError] = useState<{ id: string; message: string } | null>(null);

  // Data of another task (the id changed) is never shown.
  const execution = state.id === executionId ? state.execution : null;
  const error = state.id === executionId ? state.error : null;
  const status = execution?.status;
  const polling = Boolean(executionId) && (status === undefined || shouldPoll(status));
  const active = Boolean(executionId) && (status === undefined || isActiveStatus(status));

  // reload(): one fresh check even when polling is paused (e.g. waiting for approval).
  const forceCheck = useRef(false);

  useEffect(() => {
    if (!executionId) return;
    if (!polling && !forceCheck.current) return;
    forceCheck.current = false;
    const id = executionId;
    let stopped = false;
    let timer: number | undefined;
    let failures = 0;

    async function tick() {
      try {
        const next = await agentApi.execution(id);
        if (stopped) return;
        failures = 0;
        setState({ id, execution: next, error: null });
        if (!shouldPoll(next.status)) return;
      } catch (err) {
        if (stopped) return;
        setState((prev) => ({ id, execution: prev.id === id ? prev.execution : null, error: err }));
        if (isFatal(err)) return;
        failures += 1;
      }
      const delay = failures ? Math.min(POLL_INTERVAL_MS * 2 ** failures, MAX_BACKOFF_MS) : POLL_INTERVAL_MS;
      timer = window.setTimeout(tick, delay);
    }

    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [executionId, polling, version]);

  // An unfinished task keeps the app "busy" (lib/busy.ts).
  useEffect(() => {
    if (!active) return;
    return beginBusy();
  }, [active]);

  const onFinalRef = useRef(onFinal);
  useEffect(() => {
    onFinalRef.current = onFinal;
  });
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (!execution || !isFinalStatus(execution.status) || reported.current === execution.id) return;
    reported.current = execution.id;
    onFinalRef.current?.(execution);
  }, [execution]);

  const reload = useCallback(() => {
    forceCheck.current = true;
    setVersion((v) => v + 1);
  }, []);

  const act = useCallback(
    async (action: AgentAction, call: (id: string) => Promise<AgentExecution>) => {
      if (!executionId) return;
      const id = executionId;
      setActing(action);
      setActionError(null);
      try {
        const next = await call(id);
        setState({ id, execution: next, error: null });
      } catch (err) {
        setActionError({ id, message: err instanceof Error ? err.message : "That didn't work. Please try again." });
        // The task may have moved on (e.g. it timed out): show its real state.
        reload();
      } finally {
        setActing(null);
      }
    },
    [executionId, reload],
  );

  return {
    execution,
    error,
    active,
    reload,
    acting,
    actionError: actionError && actionError.id === executionId ? actionError.message : null,
    cancel: () => act("cancel", (id) => agentApi.cancel(id)),
    confirm: (actionId: string) => act("confirm", (id) => agentApi.confirm(id, actionId)),
    reject: (actionId: string) => act("reject", (id) => agentApi.reject(id, actionId)),
    answerMemory: (proposalId: string, save: boolean) =>
      act(save ? "save_memory" : "discard_memory", (id) => agentApi.answerMemoryProposal(id, proposalId, save)),
  };
}

export type AgentExecutionHandle = ReturnType<typeof useAgentExecution>;
