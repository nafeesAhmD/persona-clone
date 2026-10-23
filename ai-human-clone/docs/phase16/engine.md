# Phase 16 — Agent engine

The AI agent is a **controlled, multi-step assistant** attached to a clone. It can only call the
registered tools in `app/agent/tools/*` (knowledge search, approved memories, clone info,
conversation context, calculator, date/time, optional web search). **The AI agent does not have
unrestricted access to the computer or server**: there is no shell, code execution, file system,
database, environment-variable or arbitrary HTTP tool. Forbidden names (`run_shell`, `exec`, `sql`, …)
can't even be registered.

## Architecture

```
POST run ──> service.start_execution ──> runner.submit ──> worker thread (own DB session)
                                                     └──> agent.AgentRun.run()
   goal ─> planner (LLM generate_json, strict schema) ─> tool_permissions.check_tool_call
        ─> tool.validate ─> [confirmation pause] ─> executor (timeout, retries)
        ─> observation (untrusted, size-capped) ─> planner ... ─> final answer (clone persona)
```

| File | Role |
|------|------|
| `service.py` | API-facing operations: profile, start, cancel, confirm/reject, memory decision, `to_read` |
| `runner.py` | In-process worker pool (`WORKERS=2`), `INLINE` mode for tests, app-loop bridge for async provider calls, startup recovery |
| `agent.py` | The bounded plan → act → observe loop, limits, statuses, records, usage/audit events |
| `planner.py` | One `generate_json` call per step; strict parsing into `PlannerDecision`; one re-ask on invalid output |
| `executor.py` | Runs a tool in a thread with a timeout; retries only low-risk tools |
| `prompts.py` | Security boundary, planner rules, JSON schema, final-answer addendum |
| `context.py` | Planner message and final-answer context within `AGENT_MAX_CONTEXT_CHARS` |
| `safety.py` | Secret redaction, `<untrusted_data>` wrapping, safe previews |
| `state.py` | Counters rebuilt from steps, loop-detection signatures, in-process observation cache |

The LLM is the existing provider (`app.ai.factory.get_llm_provider()`); there is no second client.

## Statuses

`queued → planning ⇄ running → completed`, or `waiting_confirmation` (paused for the user), or the
final `failed | cancelled | timeout`. At startup `runner.recover_interrupted()` marks runs left
`queued/planning/running` as `failed`. Runs in `waiting_confirmation` stay waiting, because confirming
them resumes the run.

## Limits (never unlimited)

| Limit | Value | Outcome |
|-------|-------|---------|
| Steps (planner decisions) | `min(profile.max_steps, AGENT_MAX_STEPS)` | `failed` – "reached its step limit" |
| Tool calls | `AGENT_MAX_TOOL_CALLS` (retries don't count) | `failed` – "reached its tool-call limit" |
| Active wall time | `min(profile.max_execution_time_seconds, AGENT_MAX_EXECUTION_TIME_SECONDS)` | `timeout` |
| Tool attempt | `min(tool.timeout_seconds, time left)` | the attempt fails; at the run limit → `timeout` |
| Planner call | the time left | `timeout` |
| Context | `AGENT_MAX_CONTEXT_CHARS`, each observation ≤ ¼ of it, oldest dropped first | — |
| Monthly runs | plan limit `agent_executions` (counted per clone owner or organization) | 429 `usage_limit_reached` |

When the run hits the step or tool-call limit it **fails with a safe explanation**. It does not write a
partial answer. Time spent waiting for the user's confirmation doesn't count toward the time limit.

## Loop detection

- The same tool with the same **normalised** arguments (case and whitespace folded, keys sorted) may
  be requested at most **twice**. A third request stops the run.
- **Three** empty or failed tool results in a row stop the run.
- Both end as `failed` with "Agent stopped because it could not make further progress."

## Retries

- Only **low-risk** tools are retried automatically, up to `AGENT_MAX_TOOL_RETRIES` extra attempts,
  when the tool returns `ok=false` or raises. A timeout is never retried.
- **Medium and higher risk tools are never retried automatically.** They run at most once for each approved call.
- Errors are reduced to safe messages ("The tool failed."). Exception text and stack traces never
  reach the planner, the steps or the API.

## Confirmation

`tool_permissions.check_tool_call` decides `needs_confirmation`, which is required by default for
medium+ risk. When confirmation is needed, the run stores
`pending_action = {action_id (uuid4 hex), tool, title, reason, risk, input_preview}` plus internal fields
(the exact arguments, never returned by the API), records a `confirmation` step (`waiting`), sets
`waiting_confirmation` and frees the worker.

- `confirm(action_id)` must match exactly (constant-time compare). The id is consumed at once, and
  the run is resubmitted to execute **exactly that call**. Permissions and arguments are checked again
  first, in case the settings changed in the meantime.
- A wrong or stale action id, or a replay of a used one, raises `ConfirmationError`.
- `reject(action_id)` records the step as `rejected`. The planner is told the user declined. If it asks
  for the same call again, the step is `skipped` and the tool doesn't run.
- `cancel` while waiting ends the run immediately (`cancelled`).

## Cancellation

`cancel` sets `cancel_requested`. The loop checks it before every planner call and every tool call,
so no new tool call starts after a cancel. A queued or waiting run is cancelled immediately.

## Memory suggestions

The planner may return `propose_memory`. The engine stores
`memory_proposal = {proposal_id, content, memory_type}` **only on owner runs** and refuses anything
`memory_safety.looks_sensitive` flags (passwords, keys, card numbers…). It never saves or approves a
memory itself. `decide_memory_proposal(save=True)` is the explicit user approval: only the clone owner
may save, and the memory goes through `memory_service.create_manual` (the Phase 6 path for a memory the
owner approved, with its secret and duplicate checks). `save=False` dismisses it. Either way the
suggestion is cleared.

## Prompt-injection defence

- The trust order is stated in the planner's system prompt (`SECURITY BOUNDARY`): agent rules, then the
  clone's configuration, then the user's goal.
- Tool outputs (documents, knowledge, memories, conversation text, web results) reach the planner only
  inside `<untrusted_data source="tool:…">` blocks, and the prompt says they are data, never instructions.
  Our own tags inside the data are defused, so data can't close a block early.
- The tool list in the system prompt comes only from the registry. Unknown or forbidden tools requested by
  the planner are refused (`ToolNotFoundError` / `ToolNotAllowedError`), recorded as a failed step and a
  `tool_failed` audit event.
- `safety.redact` removes secret-shaped strings (provider keys, JWTs, private keys, long random tokens,
  card numbers) and the server's own configured secrets (API keys, JWT secret, database URL…). It runs on
  everything shown to the planner and everything stored: step metadata, errors, the result summary and
  the final answer.
- Steps store only short public summaries, sizes, counts, an argument preview of at most 120 characters,
  and a hash of the arguments. They never store tool output, private messages or the planner's raw output.
  `to_read` returns each step's `summary` only. Chain-of-thought is never stored.

## Final answer and conversations

The planner's `final` answer is a draft. The engine writes the real answer with one
`generate_response` call using `build_clone_system_prompt(clone, owner_name)` plus an agent addendum,
so it follows the clone's persona. The gathered results are passed as reference knowledge. If that call
fails or time is up, the redacted draft is used instead.

- `start_execution` creates or validates the conversation **before** the run starts, as the acting user
  and clone (404 for someone else's). It saves the goal as a `user` message (with `input_mode`
  `text`/`voice`) and sets `execution.conversation_id` immediately. The conversation source is `api`
  for developer-API runs and `app` otherwise.
- On completion the answer is saved as an `assistant` message, and `final_message_id` and
  `result_summary` are set. Voice and avatar reuse that message.
- **Org editor runs:** the conversation belongs to the **acting user** (the clone owner) that the API
  passes. `conversation_service` only lets the conversation's owner read it, so an editor requester
  **cannot** open it (404). The frontend should show `result_summary` from the execution instead.
- Public runs (`source="public"`) don't write to owner conversations.

## Usage and audit

- Usage: `AGENT_EXECUTION` (provider = LLM name, status `success|failed|cancelled|timeout`,
  `duration_ms`, `output_units` = steps), `AGENT_TOOL_CALL` per attempt (provider = tool name),
  `AGENT_ERROR` on `failed`/`timeout`.
- Security (low severity; details = execution id, tool, status, never secrets): `agent_started`,
  `tool_called`, `tool_failed`, `confirmation_requested/approved/rejected`,
  `agent_completed/cancelled/timeout/failed`, `agent_memory_decided`.

## Background execution

`runner.submit(id)` queues the run on a 2-thread pool and returns at once, so the API request never
waits. Async provider calls from worker threads run on the API's event loop (same pattern as avatar jobs).
The app must call this at startup:

```python
from app.agent import runner as agent_runner
agent_runner.set_event_loop(asyncio.get_running_loop())
agent_runner.recover_interrupted()
```

Tests set `runner.INLINE = True`, which runs the whole run synchronously in the caller.
