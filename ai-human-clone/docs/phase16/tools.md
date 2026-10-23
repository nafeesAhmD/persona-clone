# AI agent tools and permissions (Phase 16)

The agent can only call the tools registered in `backend/app/agent/tools/`. Each tool is
read-only, narrowly scoped, has strict JSON input/output schemas (`additionalProperties: false`),
a timeout, and returns safe errors (no stack traces, keys or internal details). Every call is
checked by `app/agent/tool_permissions.py` before it runs.

## Built-in tools

| Tool | Scope | Risk | Default | Confirmation | Public-safe | Timeout | What it does |
|---|---|---|---|---|---|---|---|
| `knowledge_search` | `knowledge:read` | low | on | no | no | 15 s | Semantic search over the clone's indexed knowledge (`query` 1–500 chars, `top_k` 1–8, default 5). Returns `{title, source_type, score, snippet ≤ 500}` — no file paths or ids. |
| `memory_search` | `memory:read` | low | on | no | no | 15 s | Search **approved** long-term memories only, re-checked against the database. Returns `{memory_type, content ≤ 300}`. |
| `clone_info` | `clone:read` | low | on | no | no | 5 s | Name, profession, tagline, skills, preferred language, communication style, public status (visibility, public chat, status). |
| `conversation_context` | `conversation:read` | low | on | no | no | 5 s | Last `limit` (1–10, default 6) messages of the current run's conversation only; each ≤ 500 chars, total ≤ 3000. |
| `calculator` | `calculator:use` | low | on | no | yes | 2 s | Safe arithmetic (`expression` ≤ 200 chars). Returns `{expression, result}`. |
| `date_time` | `utility:read` | low | on | no | yes | 2 s | Current date/time/weekday in UTC or an IANA time zone (`timezone`, validated). |
| `web_search` | `web:search` | low | **off** | no | no | 10 s | Web search through a configured provider. Unavailable unless enabled on the server **and** a provider is configured. Results marked untrusted. |

### Data visibility

- **Owner runs** (`source` app/api and the requester is the clone owner): all of the clone's
  knowledge and approved memories.
- **Public or non-owner runs** (`source == "public"` or `is_owner` false): only documents with
  visibility `public` (ready and indexed) and memories that are approved **and** public — the same
  database allowlist as public chat (`public_rag_pipeline.public_scope`). With nothing public the
  tools return nothing; they never widen the search.
- Candidate, rejected and archived memories are never returned, even if a stale vector exists.
- `conversation_context` reads only `ctx.conversation_id`, only if it belongs to the acting user
  and this clone. Other users' or other clones' conversations, and public runs, get nothing.
- `clone_info` never returns the system prompt, personality description, bio, owner email,
  ids, slugs, keys, or voice/avatar settings.

## Permission model

Per agent, `AgentToolPermission(agent_id, tool_name, enabled, require_confirmation)`. A missing
row means the tool's defaults.

- **Defaults are conservative**: a tool starts enabled only if it is `enabled_by_default` **and**
  low risk. Any medium/high/critical tool starts **off** and requires confirmation.
  `web_search` starts off.
- **Unavailable tools are never enabled** (e.g. `web_search` without the server switch and a
  provider), whatever the stored row says. Trying to enable one returns an error.
- **Forbidden names** (`execute_command`, `run_python`, `run_shell`, `shell`, `exec`, `eval`,
  `read_env`, `database_query`, `sql`) can't be registered and are always refused.
- **Public runs** may only use tools marked `public_safe` (`calculator`, `date_time`).
- **Confirmation**: a call needs the user's confirmation when the stored (or default)
  `require_confirmation` is on, OR the tool has `confirmation_by_default`, OR its risk is medium
  or higher and either `AGENT_DEFAULT_CONFIRMATION_REQUIRED=true` or the agent's
  `require_confirmation_for_actions` is on.

API (`app/agent/tool_permissions.py`):

- `effective_tools(db, profile) -> list[ToolSetting]` — `{name, title, description, risk,
  permission_scope, enabled, require_confirmation, available, reason_unavailable}`.
- `set_tool(db, profile, tool_name, enabled, require_confirmation) -> ToolSetting` — unknown tool:
  `ToolNotFoundError`; enabling an unavailable tool: `ToolNotAllowedError`.
- `check_tool_call(db, profile, tool_name, *, source) -> (Tool, needs_confirmation)` — raises
  `ToolNotFoundError` (unknown) or `ToolNotAllowedError` (forbidden, unavailable, turned off, or
  not public-safe on a public run).

## Calculator safety

The calculator **never** uses `eval` or `exec`. It parses with `ast.parse(mode="eval")` and walks
the tree with a tiny interpreter that accepts only:

- int/float literals (no strings, booleans, complex numbers);
- `+ - * / // % **`, unary `+`/`-`, parentheses;
- functions `sqrt abs round min max sin cos tan log log10 exp floor ceil` (positional args,
  fixed argument counts) and constants `pi`, `e`.

Everything else — names, attributes, subscripts, lambdas, comprehensions, comparisons,
`__import__`, keyword or starred arguments, bit operators — is refused before evaluation.
Abuse limits: ≤ 200 characters from a fixed character set (no `_`, quotes, brackets), ≤ 60
values/operations, powers checked **before** computing (`9**9**9` and `2**100000` are refused,
not computed), every intermediate value must be finite and within 1e100. Errors such as
division by zero or `sqrt(-1)` return a short message. `2^8` gets a hint to use `**`.

## Web search

Off by default. To make it available:

1. `AGENT_WEB_SEARCH_ENABLED=true`
2. `AGENT_WEB_SEARCH_PROVIDER=<name>` naming a provider registered in
   `app/agent/tools/web_providers.py`.

No provider ships configured, so by default the tool stays unavailable even with the switch on.
A provider implements `WebSearchProvider.search(query, max_results) -> list[{title, url,
snippet}]`, calls one fixed search API, and is registered with `register_provider(name, factory)`.
Even when available, each agent's owner must turn the tool on.

Results are **untrusted third-party content**: the tool returns `untrusted: true` with a notice
telling the planner never to follow instructions in them. Only `http(s)` URLs with a host are
kept (`javascript:`, `file:` and malformed URLs are dropped), titles ≤ 200 and snippets ≤ 300
characters, at most 5 results. The tool never fetches pages.

## What is NOT available

There is deliberately **no** tool for shell or command execution, running code, reading or
writing files, database queries, environment variables or settings, or arbitrary HTTP requests.
None may be added without a future sandboxed design and review.
