# Phase 16 contract (shared by the engine, tools, API and frontend work)

## Ownership of files
- Engine (A): app/agent/{agent,planner,executor,prompts,safety,context,state,runner,service}.py, tests/test_agent_engine.py
- Tools (B): app/agent/tools/*.py, app/agent/tool_permissions.py, tests/test_agent_tools.py
- API (C): app/agent/access.py, app/api/routes/agent.py, app/api/v1/agent.py, app/schemas/agent.py, analytics endpoint, developer scopes, router wiring is done by the lead, tests/test_agent_api.py
- Frontend (D): app/clone/[id]/agent/**, components/agent/**, lib/agentApi.ts, types/agent.ts, chat Agent Mode in components/chat/*, analytics agent section, developer docs scopes
- Lead: models (app/models/agent.py), migration 0019, config, app/agent/{schemas,exceptions,tool_registry}.py, conftest, main.py/router.py wiring, README.

## Tool permissions (B) — app/agent/tool_permissions.py
- `effective_tools(db, profile) -> list[ToolSetting]` where ToolSetting = {name, title, description, risk, permission_scope, enabled, require_confirmation, available, reason_unavailable}. Missing row = tool defaults (`enabled_by_default`, `confirmation_by_default`). A tool that isn't `available()` is never enabled.
- `set_tool(db, profile, tool_name, enabled, require_confirmation) -> ToolSetting` — unknown tool -> ToolNotFoundError; enabling an unavailable tool -> ToolNotAllowedError.
- `check_tool_call(db, profile, tool_name, *, source) -> (Tool, needs_confirmation: bool)` — raises ToolNotFoundError / ToolNotAllowedError. needs_confirmation = row.require_confirmation OR tool.risk >= MEDIUM (when settings.agent_default_confirmation_required or profile.require_confirmation_for_actions) OR tool.confirmation_by_default. Public runs: only `public_safe` tools.

## Tools (B) — names and scopes
knowledge_search (knowledge:read, low), memory_search (memory:read, low; approved only), clone_info (clone:read, low), conversation_context (conversation:read, low; capped), calculator (calculator:use, low; AST parser, no eval), date_time (utility:read, low), web_search (web:search, low; disabled unless AGENT_WEB_SEARCH_ENABLED, provider abstraction).

## Engine (A)
- Planner uses the existing provider: `factory.get_llm_provider().generate_json(system, user, schema)` → PlannerDecision. No second LLM client.
- Limits: profile.max_steps (≤ AGENT_MAX_STEPS), AGENT_MAX_TOOL_CALLS, profile.max_execution_time_seconds (≤ AGENT_MAX_EXECUTION_TIME_SECONDS), AGENT_MAX_CONTEXT_CHARS, AGENT_MAX_TOOL_RETRIES; loop detection; statuses per app/models/agent.py.
- Final answer saved as an assistant Message in a conversation (source "app"/"api" like chat) → execution.final_message_id, so voice (speech) and avatar video reuse it.
- Usage events: AGENT_EXECUTION, AGENT_TOOL_CALL, AGENT_ERROR; security/audit events via monitoring.security (agent_started, tool_called, tool_failed, confirmation_requested/approved/rejected, agent_completed/cancelled/timeout) — no secrets.

## API (C) — JSON shapes (frontend builds against these)
All require the cookie session; access per app/agent/access.py (owner; org owner/admin configure; editor run; viewer run only if allow_viewer_use).
- GET  /api/clones/{clone_id}/agent → AgentProfileRead
  {id, clone_id, name, description, enabled, max_steps, max_execution_time_seconds, require_confirmation_for_actions,
   allow_viewer_use, public_agent_enabled, platform_enabled (AGENT_ENABLED), can_configure, can_run,
   limits: {max_steps, max_execution_time_seconds, max_tool_calls}, tools: [ToolSetting]}
- PATCH /api/clones/{clone_id}/agent {enabled?, name?, description?, max_steps?, max_execution_time_seconds?,
   require_confirmation_for_actions?, allow_viewer_use?, public_agent_enabled?} → AgentProfileRead  (configure permission)
- PUT  /api/clones/{clone_id}/agent/tools/{tool_name} {enabled, require_confirmation} → ToolSetting
- POST /api/clones/{clone_id}/agent/run {goal (1..4000), conversation_id?, input_mode?: "text"|"voice"} → 202 {execution_id, status}
- GET  /api/clones/{clone_id}/agent/executions?page=1&limit=20 → {items: [ExecutionSummary], page, limit, total}
  ExecutionSummary = {id, status, goal (≤200 chars), total_steps, created_at, completed_at, source}
- GET  /api/agent/executions/{execution_id} → ExecutionRead
  {id, clone_id, status, goal, current_step, total_steps, tool_calls, result_summary, error,
   requires_confirmation, pending_action: {action_id, tool, title, reason, risk, input_preview} | null,
   memory_proposal: {proposal_id, content, memory_type} | null,
   steps: [{step_number, step_type, tool_name, status, summary, duration_ms, created_at}],
   conversation_id, final_message_id, started_at, completed_at, created_at}
- POST /api/agent/executions/{id}/cancel → ExecutionRead
- POST /api/agent/executions/{id}/confirm {action_id} → ExecutionRead; /reject {action_id} → ExecutionRead
- POST /api/agent/executions/{id}/memory-proposal {proposal_id, save: bool} → ExecutionRead
- GET  /api/clones/{clone_id}/analytics/agent?range=7d|30d|90d → {range, executions, completed, failed, cancelled,
   timeout, avg_duration_ms, avg_steps, tools: [{tool, calls, failures, failure_rate}]}
- Developer API: POST /api/v1/clones/{clone_id}/agent/run (scope agent:run) → 202 {execution_id, status};
  GET /api/v1/agent/executions/{execution_id} (scope agent:read) → ExecutionRead (developer error format).
Errors: 403 when the agent is off ("The AI agent is turned off for this clone."), 429 usage_limit, 404 for others' executions.
