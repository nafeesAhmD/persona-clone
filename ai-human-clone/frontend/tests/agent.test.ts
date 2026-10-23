import assert from "node:assert/strict";
import test from "node:test";

import {
  GOAL_MAX_LENGTH,
  agentAvailability,
  availabilityMessage,
  canUseAgentMode,
  clampInt,
  failureRatePercent,
  formatDurationMs,
  formatInputPreview,
  hasMemoryProposal,
  isActiveStatus,
  isConfirmationPending,
  isFinalStatus,
  normalizeRisk,
  outcomeMessage,
  pageCount,
  recentSteps,
  riskIcon,
  riskLabel,
  shouldPoll,
  sortToolUsage,
  statusIcon,
  statusLabel,
  statusTone,
  stepStatusLabel,
  stepTypeLabel,
  toolLockReason,
  toolTitle,
  validateGoal,
} from "../lib/agentStatus.ts";

const ALL = ["queued", "planning", "running", "waiting_confirmation", "completed", "failed", "cancelled", "timeout"];

test("only queued, planning and running are polled", () => {
  assert.deepEqual(
    ALL.filter((s) => shouldPoll(s)),
    ["queued", "planning", "running"],
  );
  assert.equal(shouldPoll("waiting_confirmation"), false);
  assert.equal(shouldPoll(undefined), false);
  assert.equal(shouldPoll(null), false);
});

test("final and active statuses", () => {
  assert.deepEqual(
    ALL.filter((s) => isFinalStatus(s)),
    ["completed", "failed", "cancelled", "timeout"],
  );
  assert.ok(isActiveStatus("waiting_confirmation"));
  assert.ok(isActiveStatus("running"));
  assert.ok(!isActiveStatus("completed"));
  assert.ok(!isActiveStatus(undefined));
});

test("status labels, tones and icons", () => {
  assert.equal(statusLabel("waiting_confirmation"), "Waiting for your approval");
  assert.equal(statusLabel("timeout"), "Timed out");
  assert.equal(statusLabel("something_new"), "something new");
  assert.equal(statusTone("running"), "active");
  assert.equal(statusTone("waiting_confirmation"), "waiting");
  assert.equal(statusTone("completed"), "success");
  assert.equal(statusTone("failed"), "error");
  assert.equal(statusTone("timeout"), "error");
  assert.equal(statusTone("cancelled"), "neutral");
  for (const status of ALL) assert.ok(statusIcon(status).length > 0, status);
});

const action = { action_id: "a1", tool: "web_search", title: "Search the web", reason: "r", risk: "medium" as const, input_preview: null };

test("confirmation is pending only with an action and an unfinished run", () => {
  assert.ok(isConfirmationPending({ status: "waiting_confirmation", requires_confirmation: true, pending_action: action }));
  assert.ok(!isConfirmationPending({ status: "waiting_confirmation", requires_confirmation: true, pending_action: null }));
  assert.ok(!isConfirmationPending({ status: "completed", requires_confirmation: true, pending_action: action }));
  assert.ok(!isConfirmationPending({ status: "running", requires_confirmation: false, pending_action: action }));
  assert.ok(!isConfirmationPending(null));
});

test("memory proposal detection", () => {
  assert.ok(hasMemoryProposal({ memory_proposal: { proposal_id: "p", content: "Likes tea", memory_type: "preference" } }));
  assert.ok(!hasMemoryProposal({ memory_proposal: null }));
  assert.ok(!hasMemoryProposal(undefined));
});

test("risk labels never rely on color alone and unknown risk isn't low", () => {
  assert.equal(riskLabel("low"), "Low risk");
  assert.equal(riskLabel("critical"), "Critical risk");
  assert.equal(normalizeRisk("weird"), "medium");
  assert.equal(normalizeRisk(undefined), "medium");
  assert.notEqual(riskIcon("low"), riskIcon("high"));
  assert.ok(riskIcon("medium").length > 0);
});

test("step labels", () => {
  assert.equal(stepTypeLabel("tool"), "Tool");
  assert.equal(stepTypeLabel("memory_proposal"), "Memory suggestion");
  assert.equal(stepTypeLabel("new_kind"), "new kind");
  assert.equal(stepStatusLabel("succeeded"), "Done");
  assert.equal(stepStatusLabel("rejected"), "Rejected");
});

test("tool titles", () => {
  assert.equal(toolTitle("knowledge_search"), "Knowledge search");
  assert.equal(toolTitle("calculator", [{ name: "calculator", title: "Calculator" }]), "Calculator");
  assert.equal(toolTitle(null), "");
});

test("durations", () => {
  assert.equal(formatDurationMs(120), "120 ms");
  assert.equal(formatDurationMs(2400), "2.4 s");
  assert.equal(formatDurationMs(65_000), "1 min 5 s");
  assert.equal(formatDurationMs(120_000), "2 min");
  assert.equal(formatDurationMs(null), "");
  assert.equal(formatDurationMs(-5), "");
});

test("failure rate from counts, or from the API value in either scale", () => {
  assert.equal(failureRatePercent({ calls: 4, failures: 1, failure_rate: 0.25 }), 25);
  assert.equal(failureRatePercent({ calls: 0, failures: 0, failure_rate: 0.5 }), 50);
  assert.equal(failureRatePercent({ calls: 0, failures: 0, failure_rate: 40 }), 40);
  assert.equal(failureRatePercent({ calls: 0, failures: 0, failure_rate: 0 }), 0);
  assert.equal(failureRatePercent({ calls: 2, failures: 5, failure_rate: 1 }), 100);
});

test("tool usage is sorted by calls", () => {
  const sorted = sortToolUsage([
    { tool: "b", calls: 1 },
    { tool: "a", calls: 5 },
    { tool: "c", calls: 5 },
  ]);
  assert.deepEqual(
    sorted.map((t) => t.tool),
    ["a", "c", "b"],
  );
});

test("numbers are clamped to the server limits", () => {
  assert.equal(clampInt(12, 1, 8), 8);
  assert.equal(clampInt(0, 1, 8), 1);
  assert.equal(clampInt(3.6, 1, 8), 4);
  assert.equal(clampInt(Number.NaN, 5, 60), 5);
  assert.equal(clampInt(10, 5, 2), 5);
});

test("goal validation", () => {
  assert.ok(validateGoal("   "));
  assert.equal(validateGoal("Plan my week"), null);
  assert.equal(validateGoal("x".repeat(GOAL_MAX_LENGTH)), null);
  assert.ok(validateGoal("x".repeat(GOAL_MAX_LENGTH + 1)));
});

test("availability: server switch, clone switch, permission", () => {
  assert.equal(agentAvailability({ platform_enabled: false, enabled: true, can_run: true }), "platform_off");
  assert.equal(agentAvailability({ platform_enabled: true, enabled: false, can_run: true }), "agent_off");
  assert.equal(agentAvailability({ platform_enabled: true, enabled: true, can_run: false }), "no_access");
  assert.equal(agentAvailability({ platform_enabled: true, enabled: true, can_run: true }), "ready");
  assert.equal(agentAvailability(null), "no_access");
  assert.ok(canUseAgentMode({ platform_enabled: true, enabled: true, can_run: true }));
  assert.ok(!canUseAgentMode({ platform_enabled: false, enabled: true, can_run: true }));
  assert.match(availabilityMessage("platform_off", true), /server/);
  assert.match(availabilityMessage("agent_off", true), /Turn it on/);
  assert.doesNotMatch(availabilityMessage("agent_off", false), /Turn it on/);
});

test("tool lock reasons", () => {
  assert.equal(toolLockReason({ available: false, reason_unavailable: "Web search is off on this server." }, true), "Web search is off on this server.");
  assert.ok(toolLockReason({ available: false, reason_unavailable: null }, true));
  assert.ok(toolLockReason({ available: true, reason_unavailable: null }, false));
  assert.equal(toolLockReason({ available: true, reason_unavailable: null }, true), null);
});

test("outcome messages", () => {
  assert.equal(outcomeMessage({ status: "failed", error: "Tool failed" }), "Tool failed");
  assert.ok(outcomeMessage({ status: "timeout", error: null }));
  assert.ok(outcomeMessage({ status: "cancelled", error: null }));
  assert.equal(outcomeMessage({ status: "completed", error: null }), null);
});

test("input previews are always text", () => {
  assert.equal(formatInputPreview("2 + 2"), "2 + 2");
  assert.equal(formatInputPreview({ query: "tea" }), JSON.stringify({ query: "tea" }, null, 2));
  assert.equal(formatInputPreview(null), "");
  assert.equal(formatInputPreview("x".repeat(10), 4), "xxxx…");
});

test("pagination and recent steps", () => {
  assert.equal(pageCount(0, 20), 1);
  assert.equal(pageCount(41, 20), 3);
  assert.equal(pageCount(5, 0), 1);
  const steps = [3, 1, 2, 5, 4].map((n) => ({ step_number: n }));
  const { shown, hidden } = recentSteps(steps, 3);
  assert.deepEqual(
    shown.map((s) => s.step_number),
    [3, 4, 5],
  );
  assert.equal(hidden, 2);
});
