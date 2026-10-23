# Phase 16 — AI agent: frontend notes

The controlled AI agent lets a clone work on a task in a few **visible steps**, using only the tools its owner turned on, within the owner's step and time limits. It never shows the model's private reasoning: the API sends short step summaries only, and the UI shows only those.

## Agent page — `/clone/[id]/agent`

Linked from the clone details page ("AI Agent" card). Mobile back button: `/clone/[id]/agent` → clone details; a task page → the agent page.

- **Status**: two badges — *Server* (`AGENT_ENABLED`) and *This clone* — plus a plain sentence:
  - server off: "The AI agent is turned off on this server…" (the switch is locked);
  - clone off: "Turn it on below to run tasks" (owners/admins) or "turned off for this clone" (others);
  - no permission: "You don't have permission to run this clone's agent."
- **Turn on the AI agent** switch (only when `can_configure`).
- **Settings** (only when `can_configure`, otherwise read-only): name, description, maximum steps and maximum time (bounded by the server limits shown under each field), *Ask before actions*, *Let organization viewers use the agent* (org clones), and — owner only — *Public agent* (off by default; in this version the agent is not offered to public visitors even when on). Saved with one **Save settings** button.
- **Tools**: each tool with its title, description, permission scope and a risk badge (icon + text, never color alone), and two switches: **Enabled** and **Ask first**. Tools the server doesn't offer (e.g. Web Search without `AGENT_WEB_SEARCH_ENABLED`) are shown locked with the reason.
- **Run a task**: a goal (up to 4000 characters, with a counter). The running task appears below with live steps.
- **Task history**: newest first, 10 per page, each linking to its task page.

## Task page — `/clone/[id]/agent/executions/[executionId]`

- Goal, status badge, steps ("Step 1 · Tool · Knowledge search · Done · 120 ms" + summary), result, error and timing facts.
- Checked every 1.5 s while the task is `queued`, `planning` or `running`; polling stops on `completed`, `failed`, `cancelled`, `timeout` and while it is `waiting_confirmation` (it resumes after Confirm/Reject). Errors back off up to 10 s.
- **Cancel task** while unfinished.
- While a task is unfinished the app is marked busy (`lib/busy.ts`), so a PWA update never reloads the page mid-run.
- Status changes are announced through an `aria-live` region.

## Confirmations

When the agent wants to use a tool that needs approval, the task pauses (`waiting_confirmation`) and a card appears:

> ✋ **AI wants to perform this action.** — action title, tool, risk, why, and a preview of the input — **Reject** / **Confirm**

The buttons send the `action_id` from `pending_action`, so an old card can't approve a different action. Keyboard focus moves to the card when it appears.

## Memory proposals

If the agent learns something worth remembering it never saves it on its own. A card asks:

> 🧠 I learned that "…". Would you like me to save this? — **Don't save** / **Save**

## Agent Mode in the chat

- A **Normal Chat / Agent Mode** switch appears above the composer only when the clone's agent is on and the viewer can run it (`GET /api/clones/{id}/agent`, fetched once; any error hides it). Normal Chat is unchanged.
- In Agent Mode a message starts `POST /api/clones/{id}/agent/run` with `{goal, conversation_id, input_mode}`. A compact live step list (newest 4 steps) shows under your message, with Cancel, the confirmation card and the memory card inline.
- When the task completes, its final answer — saved on the server as a normal assistant message (`final_message_id`) — is added to the chat. Then, as for any answer: **Voice** reply mode speaks it with the existing speech flow, **Avatar** mode makes the talking-avatar video for that final message only (never for steps). Spoken questions in Agent Mode are sent with `input_mode: "voice"`.
- Failed, timed-out or cancelled tasks leave a short message in the chat.

## Analytics and developer docs

- Clone analytics has an **AI agent** section: tasks, completed / failed / timed out / cancelled, average duration and steps, and the most-used tools with their failure rate. The agent endpoint supports 7/30/90 days; "Today" and "Yesterday" show the last 7 days (noted on screen).
- The developer docs have an **Agent API** section (`POST /api/v1/clones/{id}/agent/run`, scope `agent:run`; `GET /api/v1/agent/executions/{id}`, scope `agent:read`) with curl, JavaScript and Python examples.

## Files

- `types/agent.ts`, `lib/agentApi.ts`, `lib/agentStatus.ts` (pure logic, tested in `tests/agent.test.ts`)
- `components/agent/*`: `AgentManager`, `AgentHistory`, `AgentRunView`, `AgentExecutionView`, `AgentAnalyticsSection`, `useAgentExecution`, `ui` (status/risk badges, switch)
- `app/clone/[id]/agent/page.tsx`, `app/clone/[id]/agent/executions/[executionId]/page.tsx`
- Chat: `components/chat/ChatWindow.tsx`, `components/chat/ChatModeSwitch.tsx`
