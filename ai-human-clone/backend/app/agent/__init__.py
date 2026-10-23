"""AI agent (Phase 16): a controlled, multi-step assistant built on the clone's chat.

    goal -> Agent controller (agent.py) -> Planner (planner.py, the existing LLM
    provider via generate_json) -> tool selection -> permission + safety checks
    (tool_permissions.py, safety.py) -> tool execution (executor.py, tools/*) ->
    observation -> next step ... -> final answer

The agent can ONLY call the tools registered in tool_registry.py (tools/*). There is
no shell, code execution, filesystem, database, environment or arbitrary HTTP tool,
and none may be added without a future sandboxed design. Every call is checked
against the agent's enabled tools, the caller's permissions, plan limits, step /
tool-call / time limits and the tool's input schema. Medium+ risk actions pause for
the user's confirmation. Documents, memories, web pages and tool outputs are
untrusted data, never instructions.

Modules (see each file): schemas, exceptions, state, tool_registry, tool_permissions,
tools/*, prompts, safety, context, planner, executor, agent, runner, service, access.
"""
