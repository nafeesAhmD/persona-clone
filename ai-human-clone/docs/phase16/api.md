# AI Agent API (Phase 16)

The AI agent lets a clone work through a goal in several visible steps, using only a small
set of registered, permission-checked tools (knowledge search, approved-memory search, clone
info, conversation context, calculator, date/time, and web search when the server enables it).
It never gets shell, code, file-system, environment or database access.

**Off by default, twice:** the server needs `AGENT_ENABLED=true`, and every clone's agent
starts disabled until someone with configure permission turns it on.

## Endpoints (app, cookie session)

| Method | Path | Who | Result |
|---|---|---|---|
| GET | `/api/clones/{clone_id}/agent` | any role on the clone | `AgentProfileRead` (created on first read, disabled) |
| PATCH | `/api/clones/{clone_id}/agent` | configure | `AgentProfileRead` |
| PUT | `/api/clones/{clone_id}/agent/tools/{tool_name}` | configure | `ToolSetting` |
| POST | `/api/clones/{clone_id}/agent/run` | run | **202** `{execution_id, status}` |
| GET | `/api/clones/{clone_id}/agent/executions?page=1&limit=20` | any role | `{items, page, limit, total}` |
| GET | `/api/agent/executions/{execution_id}` | view execution | `ExecutionRead` |
| POST | `/api/agent/executions/{execution_id}/cancel` | view execution | `ExecutionRead` |
| POST | `/api/agent/executions/{execution_id}/confirm` `{action_id}` | view execution + run | `ExecutionRead` |
| POST | `/api/agent/executions/{execution_id}/reject` `{action_id}` | view execution + run | `ExecutionRead` |
| POST | `/api/agent/executions/{execution_id}/memory-proposal` `{proposal_id, save}` | view + run (save: clone owner) | `ExecutionRead` |
| GET | `/api/clones/{clone_id}/analytics/agent?range=7d\|30d\|90d` | configure | agent analytics |

JSON shapes are in [contract.md](contract.md). Notes:

- **PATCH** accepts only `enabled, name, description, max_steps (1..AGENT_MAX_STEPS),
  max_execution_time_seconds (5..AGENT_MAX_EXECUTION_TIME_SECONDS),
  require_confirmation_for_actions, allow_viewer_use, public_agent_enabled`. Any other field
  is a 400 (no mass assignment).
- **Tools:** an unknown tool (including forbidden names like `run_shell`) is 404; turning on a
  tool the server can't offer (e.g. `web_search` without `AGENT_WEB_SEARCH_ENABLED`) is 400.
  `require_confirmation` may be omitted to keep the current value.
- **Run:** `{goal (1..4000 chars), conversation_id?, input_mode?: "text"|"voice"}`. A
  `conversation_id` must be one of *your own* conversations with this clone (404 otherwise).
  Runs act as the clone owner (same knowledge/memory as the owner's chat) while the execution
  records the logged-in requester. Rate limit: 10 runs per minute per user (admin override key
  `agent`). Plan limit: monthly `agent_executions` → 429.
- **Executions list:** owners and org owners/admins see every run of the clone; other members
  only their own.
- **Confirmations:** `action_id` must match the pending action; wrong, stale or replayed ids
  are 409. Steps show only a short public summary — never hidden reasoning or raw tool output.
- **Voice / avatar:** the final answer is saved as a normal assistant message
  (`final_message_id` in `conversation_id`), so the existing endpoints work on it:
  `POST /api/conversations/{conversation_id}/messages/{final_message_id}/speech` and
  `POST /api/clones/{clone_id}/avatar/video` with `{conversation_id, message_id}`.

### Errors

| Status | When |
|---|---|
| 400 | validation (unknown fields, ranges, unavailable tool) |
| 401 | not logged in |
| 403 | `"The AI agent isn't enabled on this server."`, `"The AI agent is turned off for this clone."`, missing role |
| 404 | private clone you have no role on; someone else's execution; unknown tool |
| 409 | wrong/stale confirmation `action_id` |
| 429 | too many runs per minute; monthly `agent_executions` reached (`usage_limit_reached`) |

## Permissions by role

Roles come from Phase 13 organizations (the clone must be assigned to the organization).

| Role | See settings | Configure (PATCH, tools, analytics) | Run | Public agent switch | Read others' executions |
|---|---|---|---|---|---|
| Clone owner | yes | yes | yes | **yes (only the owner)** | yes (all of the clone) |
| Org owner | yes | yes | yes | no (403) | yes (all of the clone) |
| Org admin | yes | yes | yes | no (403) | yes (all of the clone) |
| Org editor | yes | no (403) | yes | no | no — own runs only |
| Org viewer | yes | no (403) | only if `allow_viewer_use` | no | no — own runs only |
| Anyone else | 404 (private clone) / 403 | no | no | no | 404 |

Confirming or rejecting an action needs both: being able to see the execution *and* current run
permission (a viewer whose access was turned off can't approve anything). Saving a suggested
memory is clone-owner only (memories are the owner's); dismissing needs run permission.

## Public agent

`CloneProfile.public_agent_enabled` exists and defaults to **false**; only the clone owner can
change it. In this phase there is **no public (visitor) agent endpoint** — the flag has no effect
and visitors can never start agent runs. (If one is added later, it must only offer tools marked
`public_safe`, which `tool_permissions.check_tool_call(..., source="public")` already enforces.)

## Developer API

Two new API-key scopes:

| Scope | Allows |
|---|---|
| `agent:run` | `POST /api/v1/clones/{clone_id}/agent/run` |
| `agent:read` | `GET /api/v1/agent/executions/{execution_id}` |

- Keys reach only their own clones (personal key: clones the user owns; organization key:
  clones of the organization); anything else is `404 resource_not_found`.
- Runs act as the clone owner, are recorded with `source: "api"` and the key's id, and need the
  agent turned on (`403 permission_denied` otherwise). A missing scope is `403 permission_denied`.
- `GET /api/v1/agent/executions/{id}` returns only runs started through the API for the key's
  clones — the owner's in-app runs stay private (404).
- Errors use the developer format `{"error", "message", "request_id"}`.

```bash
# Start a run (202)
curl -X POST https://your-host/api/v1/clones/$CLONE_ID/agent/run \
  -H "Authorization: Bearer $AHC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"goal": "Summarise what my knowledge says about our refund policy"}'
# → {"execution_id": "6f1c...", "status": "queued"}

# Poll until status is completed / failed / cancelled / timeout
curl https://your-host/api/v1/agent/executions/$EXECUTION_ID \
  -H "Authorization: Bearer $AHC_API_KEY"
# → {"id": "...", "status": "completed", "steps": [{"step_number": 1, "step_type": "tool",
#     "tool_name": "knowledge_search", "status": "succeeded", "summary": "Searched knowledge", ...}],
#     "result_summary": "...", "final_message_id": "...", ...}
```

A run waiting for confirmation (`status: "waiting_confirmation"`) can only be approved in the app.

## Analytics

`GET /api/clones/{clone_id}/analytics/agent?range=30d` (owner or org owner/admin):

```json
{"range": "30d", "executions": 12, "completed": 9, "failed": 1, "cancelled": 1, "timeout": 1,
 "avg_duration_ms": 4200, "avg_steps": 3.25,
 "tools": [{"tool": "knowledge_search", "calls": 14, "failures": 1, "failure_rate": 0.071}]}
```

Computed from `agent_executions` / `agent_steps` counts and timings only — never goals, answers
or tool data.
