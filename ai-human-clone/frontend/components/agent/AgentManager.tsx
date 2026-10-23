"use client";

import Link from "next/link";
import { type FormEvent, useId, useState } from "react";

import { AgentHistory } from "@/components/agent/AgentHistory";
import { AgentRunView } from "@/components/agent/AgentRunView";
import { RiskBadge, Switch } from "@/components/agent/ui";
import { useAgentExecution } from "@/components/agent/useAgentExecution";
import { Card, LoadingBlock, Notice, PageShell, btnPrimary, btnSecondary, inputCls, labelCls, useApiData } from "@/components/analytics/ui";
import { ApiErrorState } from "@/components/ApiErrorState";
import { getChatProfile } from "@/lib/api";
import { agentApi } from "@/lib/agentApi";
import {
  GOAL_MAX_LENGTH,
  MIN_EXECUTION_SECONDS,
  MIN_STEPS,
  agentAvailability,
  availabilityMessage,
  clampInt,
  toolLockReason,
  validateGoal,
} from "@/lib/agentStatus";
import type { AgentProfile, AgentProfileUpdate, AgentToolSetting } from "@/types/agent";

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function AgentManager({ cloneId }: { cloneId: string }) {
  const agent = useApiData(() => agentApi.get(cloneId), cloneId);
  const clone = useApiData(() => getChatProfile(cloneId), cloneId);
  // Bumped when a task finishes so the history shows it.
  const [historyVersion, setHistoryVersion] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const run = useAgentExecution(runId, () => setHistoryVersion((v) => v + 1));

  const encodedId = encodeURIComponent(cloneId);
  const back = { href: `/clone/${encodedId}/details`, label: "Back to clone" };

  if (agent.error && !agent.data) {
    return <ApiErrorState error={agent.error} thing="AI agent" onRetry={agent.reload} />;
  }
  if (!agent.data) {
    return (
      <PageShell title="AI Agent" back={back}>
        <LoadingBlock label="Loading the AI agent…" />
      </PageShell>
    );
  }

  const profile = agent.data;
  const availability = agentAvailability(profile);
  const isOwner = clone.data?.is_owner ?? false;
  const title = clone.data ? `${clone.data.name} · AI Agent` : "AI Agent";

  return (
    <PageShell
      title={title}
      busy={run.active}
      back={back}
      description="Give your clone a task. It works in a few visible steps using only the tools you allow, and asks before risky actions."
    >
      <div className="space-y-4">
        <StatusCard profile={profile} availability={availability} onChange={agent.setData} cloneId={cloneId} />

        {profile.can_configure ? (
          <SettingsForm
            key={`${profile.id}:${profile.max_steps}:${profile.max_execution_time_seconds}:${profile.name}:${profile.description ?? ""}`}
            cloneId={cloneId}
            profile={profile}
            isOwner={isOwner}
            onSaved={agent.setData}
          />
        ) : (
          <ReadOnlySettings profile={profile} />
        )}

        <ToolList cloneId={cloneId} profile={profile} onChange={agent.setData} />

        {availability === "ready" ? (
          <RunTaskForm cloneId={cloneId} running={run.active} onStarted={setRunId} />
        ) : (
          <Card>
            <h2 className="font-semibold text-white">Run a task</h2>
            <p className="mt-1 text-sm text-muted">{availabilityMessage(availability, profile.can_configure)}</p>
          </Card>
        )}

        {runId && (
          <Card>
            <h2 className="mb-3 font-semibold text-white">Current task</h2>
            <AgentRunView
              run={run}
              tools={profile.tools}
              detailsHref={`/clone/${encodedId}/agent/executions/${encodeURIComponent(runId)}`}
            />
          </Card>
        )}

        <AgentHistory cloneId={cloneId} version={historyVersion} />
      </div>
    </PageShell>
  );
}

function StatusCard({
  cloneId,
  profile,
  availability,
  onChange,
}: {
  cloneId: string;
  profile: AgentProfile;
  availability: ReturnType<typeof agentAvailability>;
  onChange: (profile: AgentProfile) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(enabled: boolean) {
    setSaving(true);
    setError(null);
    try {
      onChange(await agentApi.update(cloneId, { enabled }));
    } catch (err) {
      setError(errorText(err, "Could not change the agent."));
    } finally {
      setSaving(false);
    }
  }

  const lockedReason = !profile.platform_enabled
    ? "Turned off on this server (AGENT_ENABLED), so it can't be switched on here."
    : null;

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold text-white">Status</h2>
        <OnOff label="Server" on={profile.platform_enabled} />
        <OnOff label="This clone" on={profile.enabled} />
      </div>
      <p
        role="status"
        aria-live="polite"
        className={`mt-2 text-sm ${availability === "ready" ? "text-emerald-200" : availability === "platform_off" ? "text-amber-200" : "text-muted"}`}
      >
        <span aria-hidden="true">{availability === "ready" ? "✓ " : "ℹ "}</span>
        {availabilityMessage(availability, profile.can_configure)}
      </p>
      {profile.can_configure && (
        <div className="mt-3 border-t border-border pt-3">
          <Switch
            label="Turn on the AI agent"
            description="When on, people who can run it can give this clone tasks in the agent page and in Agent Mode in the chat."
            checked={profile.enabled}
            onChange={(next) => void toggle(next)}
            lockedReason={lockedReason}
            busy={saving}
          />
        </div>
      )}
      {error && (
        <div className="mt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
    </Card>
  );
}

function OnOff({ label, on }: { label: string; on: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${on ? "border-emerald-500/40 text-emerald-200" : "border-border text-muted"}`}
    >
      <span aria-hidden="true">{on ? "●" : "○"}</span>
      {label}: {on ? "On" : "Off"}
    </span>
  );
}

function SettingsForm({
  cloneId,
  profile,
  isOwner,
  onSaved,
}: {
  cloneId: string;
  profile: AgentProfile;
  isOwner: boolean;
  onSaved: (profile: AgentProfile) => void;
}) {
  const id = useId();
  const [name, setName] = useState(profile.name);
  const [description, setDescription] = useState(profile.description ?? "");
  const [maxSteps, setMaxSteps] = useState(String(profile.max_steps));
  const [maxSeconds, setMaxSeconds] = useState(String(profile.max_execution_time_seconds));
  const [askFirst, setAskFirst] = useState(profile.require_confirmation_for_actions);
  const [viewers, setViewers] = useState(profile.allow_viewer_use);
  const [publicAgent, setPublicAgent] = useState(profile.public_agent_enabled);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  const stepsMax = Math.max(MIN_STEPS, profile.limits.max_steps);
  const secondsMax = Math.max(MIN_EXECUTION_SECONDS, profile.limits.max_execution_time_seconds);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setResult({ tone: "error", text: "Give the agent a name." });
      document.getElementById(`${id}-name`)?.focus();
      return;
    }
    const update: AgentProfileUpdate = {
      name: name.trim(),
      description: description.trim() || null,
      max_steps: clampInt(Number(maxSteps), MIN_STEPS, stepsMax),
      max_execution_time_seconds: clampInt(Number(maxSeconds), MIN_EXECUTION_SECONDS, secondsMax),
      require_confirmation_for_actions: askFirst,
      allow_viewer_use: viewers,
    };
    if (isOwner) update.public_agent_enabled = publicAgent;
    setSaving(true);
    setResult(null);
    try {
      const saved = await agentApi.update(cloneId, update);
      setResult({ tone: "success", text: "Agent settings saved." });
      onSaved(saved);
    } catch (err) {
      setResult({ tone: "error", text: errorText(err, "Could not save the settings.") });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <h2 className="font-semibold text-white">Settings</h2>
        <div>
          <label htmlFor={`${id}-name`} className={labelCls}>
            Name
          </label>
          <input
            id={`${id}-name`}
            type="text"
            value={name}
            maxLength={100}
            autoComplete="off"
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor={`${id}-description`} className={labelCls}>
            Description <span className="font-normal text-muted">(optional)</span>
          </label>
          <textarea
            id={`${id}-description`}
            value={description}
            maxLength={500}
            rows={3}
            onChange={(e) => setDescription(e.target.value)}
            className={`${inputCls} py-2`}
          />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor={`${id}-steps`} className={labelCls}>
              Maximum steps
            </label>
            <input
              id={`${id}-steps`}
              type="number"
              inputMode="numeric"
              min={MIN_STEPS}
              max={stepsMax}
              step={1}
              value={maxSteps}
              onChange={(e) => setMaxSteps(e.target.value)}
              onBlur={() => setMaxSteps(String(clampInt(Number(maxSteps), MIN_STEPS, stepsMax)))}
              aria-describedby={`${id}-steps-hint`}
              className={inputCls}
            />
            <p id={`${id}-steps-hint`} className="mt-1 text-xs text-muted">
              {MIN_STEPS}–{stepsMax} (server limit)
            </p>
          </div>
          <div>
            <label htmlFor={`${id}-seconds`} className={labelCls}>
              Maximum time (seconds)
            </label>
            <input
              id={`${id}-seconds`}
              type="number"
              inputMode="numeric"
              min={MIN_EXECUTION_SECONDS}
              max={secondsMax}
              step={1}
              value={maxSeconds}
              onChange={(e) => setMaxSeconds(e.target.value)}
              onBlur={() => setMaxSeconds(String(clampInt(Number(maxSeconds), MIN_EXECUTION_SECONDS, secondsMax)))}
              aria-describedby={`${id}-seconds-hint`}
              className={inputCls}
            />
            <p id={`${id}-seconds-hint`} className="mt-1 text-xs text-muted">
              {MIN_EXECUTION_SECONDS}–{secondsMax} seconds (server limit). At most {profile.limits.max_tool_calls} tool calls per task.
            </p>
          </div>
        </div>

        <div className="space-y-3 border-t border-border pt-3">
          <Switch
            label="Ask before actions"
            description="The agent stops and asks you before any action with a medium or higher risk."
            checked={askFirst}
            onChange={setAskFirst}
          />
          <Switch
            label="Let organization viewers use the agent"
            description="Only for clones that belong to an organization. Editors and admins can always run it."
            checked={viewers}
            onChange={setViewers}
          />
          {isOwner && (
            <Switch
              label="Public agent"
              description="Off by default. In this version the agent is not offered to visitors of your public chat page, even when this is on."
              checked={publicAgent}
              onChange={setPublicAgent}
            />
          )}
        </div>

        {result && <Notice tone={result.tone}>{result.text}</Notice>}
        <button type="submit" disabled={saving} className={`${btnPrimary} w-full sm:w-auto`}>
          {saving ? "Saving…" : "Save settings"}
        </button>
      </form>
    </Card>
  );
}

function ReadOnlySettings({ profile }: { profile: AgentProfile }) {
  const rows: [string, string][] = [
    ["Name", profile.name],
    ["Maximum steps", String(profile.max_steps)],
    ["Maximum time", `${profile.max_execution_time_seconds} s`],
    ["Asks before actions", profile.require_confirmation_for_actions ? "Yes" : "No"],
  ];
  return (
    <Card>
      <h2 className="font-semibold text-white">Settings</h2>
      {profile.description && <p className="mt-1 text-sm text-muted">{profile.description}</p>}
      <dl className="mt-3 divide-y divide-border text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 py-2">
            <dt className="text-muted">{label}</dt>
            <dd className="min-w-0 break-words text-right text-white">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-muted">Only the clone&apos;s owner or an organization admin can change these.</p>
    </Card>
  );
}

function ToolList({
  cloneId,
  profile,
  onChange,
}: {
  cloneId: string;
  profile: AgentProfile;
  onChange: (profile: AgentProfile) => void;
}) {
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(tool: AgentToolSetting, update: { enabled: boolean; require_confirmation: boolean }) {
    setSaving(tool.name);
    setError(null);
    try {
      const saved = await agentApi.setTool(cloneId, tool.name, update);
      onChange({ ...profile, tools: profile.tools.map((t) => (t.name === saved.name ? saved : t)) });
    } catch (err) {
      setError(`${tool.title}: ${errorText(err, "could not be changed.")}`);
    } finally {
      setSaving(null);
    }
  }

  return (
    <Card>
      <h2 className="font-semibold text-white">Tools</h2>
      <p className="mt-1 text-sm text-muted">
        The agent can only use the tools turned on here. &quot;Ask first&quot; makes it wait for your OK before using a tool.
      </p>
      {error && (
        <div className="mt-3">
          <Notice tone="error">{error}</Notice>
        </div>
      )}
      {profile.tools.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No tools are available.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {profile.tools.map((tool) => {
            const locked = toolLockReason(tool, profile.can_configure);
            const busy = saving === tool.name;
            return (
              <li
                key={tool.name}
                className={`min-w-0 rounded-xl border border-border bg-surface/60 p-3 ${tool.available ? "" : "opacity-80"}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="mr-auto min-w-0 break-words font-medium text-white">{tool.title}</h3>
                  <RiskBadge risk={tool.risk} />
                  {!tool.available && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                      <span aria-hidden="true">⊘</span> Unavailable
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted">{tool.description}</p>
                <p className="mt-1 break-all font-mono text-[11px] text-muted">{tool.permission_scope}</p>
                {!tool.available && (
                  <p className="mt-1 text-xs text-amber-200">
                    <span aria-hidden="true">ℹ </span>
                    {tool.reason_unavailable || "Not available on this server."}
                  </p>
                )}
                <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2 sm:gap-4">
                  <Switch
                    label="Enabled"
                    checked={tool.available && tool.enabled}
                    disabled={Boolean(locked)}
                    busy={busy}
                    onChange={(enabled) => void save(tool, { enabled, require_confirmation: tool.require_confirmation })}
                    description={locked && tool.available ? locked : undefined}
                  />
                  <Switch
                    label="Ask first"
                    checked={tool.require_confirmation}
                    disabled={Boolean(locked)}
                    busy={busy}
                    onChange={(require_confirmation) => void save(tool, { enabled: tool.enabled, require_confirmation })}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function RunTaskForm({
  cloneId,
  running,
  onStarted,
}: {
  cloneId: string;
  running: boolean;
  onStarted: (executionId: string) => void;
}) {
  const id = useId();
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validateGoal(goal);
    if (problem) {
      setError(problem);
      document.getElementById(`${id}-goal`)?.focus();
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const started = await agentApi.run(cloneId, { goal: goal.trim(), input_mode: "text" });
      setGoal("");
      onStarted(started.execution_id);
    } catch (err) {
      setError(errorText(err, "The task couldn't start."));
    } finally {
      setStarting(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit} noValidate className="space-y-3">
        <h2 className="font-semibold text-white">Run a task</h2>
        <div>
          <label htmlFor={`${id}-goal`} className={labelCls}>
            What should the agent do?
          </label>
          <textarea
            id={`${id}-goal`}
            value={goal}
            rows={4}
            maxLength={GOAL_MAX_LENGTH}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="e.g. Summarize what my knowledge says about my projects and list the technologies used."
            aria-invalid={error ? true : undefined}
            aria-describedby={`${id}-count${error ? ` ${id}-error` : ""}`}
            className={`${inputCls} py-2`}
          />
          <p id={`${id}-count`} className="mt-1 text-right text-xs text-muted">
            {goal.length}/{GOAL_MAX_LENGTH}
          </p>
          {error && (
            <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-rose-300">
              <span aria-hidden="true">⚠ </span>
              {error}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={starting || running || !goal.trim()} className={`${btnPrimary} w-full sm:w-auto`}>
            {starting ? "Starting…" : running ? "A task is running…" : "Run task"}
          </button>
          <Link href={`/clone/${encodeURIComponent(cloneId)}`} className={`${btnSecondary} w-full sm:w-auto`}>
            Use Agent Mode in chat
          </Link>
        </div>
      </form>
    </Card>
  );
}

