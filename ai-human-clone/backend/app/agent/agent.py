"""The agent controller: one bounded plan -> act -> observe loop per execution.

    queued -> planning -> (tool | memory suggestion | confirmation pause)* -> final answer

Every step is bounded:
- steps (planner decisions) <= min(profile.max_steps, AGENT_MAX_STEPS)          -> failed
- tool calls <= AGENT_MAX_TOOL_CALLS                                            -> failed
- active wall time <= min(profile.max_execution_time_seconds,
  AGENT_MAX_EXECUTION_TIME_SECONDS) (the time spent waiting for the user's
  confirmation doesn't count)                                                   -> timeout
- the same tool + normalised arguments requested more than twice, or three
  empty/failed results in a row                                                 -> failed ("no progress")
- cancel_requested is checked before every planner call and every tool call     -> cancelled
A limit stops the run with a safe explanation; it never produces a partial answer.

Tool calls go through tool_permissions.check_tool_call (enabled? allowed for this
source? needs confirmation?) and tool.validate on every call, including a call the user
approved. Medium+ risk calls pause the run (waiting_confirmation) with a single-use
action_id; service.confirm resumes it with exactly that call.
"""

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context, executor, planner, runner, safety
from app.agent import state as run_state
from app.agent.exceptions import ToolInputError, ToolNotAllowedError, ToolNotFoundError
from app.agent.prompts import FINAL_ADDENDUM, planner_system_prompt
from app.agent.schemas import PlannerDecision, ToolContext
from app.agent.state import NO_PROGRESS, Observation
from app.agent.tool_registry import Tool
from app.ai import factory
from app.ai.clone_prompt import build_clone_system_prompt
from app.core.config import get_settings
from app.models import CloneProfile, Conversation, User
from app.models.agent import FINAL_STATUSES, AgentExecution, AgentProfile, AgentStep
from app.services import conversation_service, monitoring

logger = logging.getLogger(__name__)

_clock = time.monotonic  # patched in tests

STEP_LIMIT = "The agent reached its step limit before finishing. Try a simpler or more specific goal."
TOOL_LIMIT = "The agent reached its tool-call limit before finishing. Try a simpler or more specific goal."
TIMEOUT = "The agent ran out of time before finishing. Try a simpler or more specific goal."
CANCELLED = "The run was cancelled."
PLANNER_FAILED = "The agent couldn't plan the next step. Please try again."
FAILED = "The agent couldn't finish this task. Please try again."
UNAVAILABLE = "The clone or its agent is no longer available."


class _Stop(Exception):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _Paused(Exception):
    """The run is waiting for the user's confirmation."""


# --- Tool permissions (app/agent/tool_permissions.py, tools work) -----------------------


def check_tool_call(db: Session, profile: AgentProfile, tool_name: str, *, source: str) -> tuple[Tool, bool]:
    from app.agent import tool_permissions

    return tool_permissions.check_tool_call(db, profile, tool_name, source=source)


def _field(setting: Any, name: str) -> Any:
    return setting.get(name) if isinstance(setting, dict) else getattr(setting, name, None)


def available_tools(db: Session, profile: AgentProfile, *, source: str) -> list[dict]:
    """Enabled + available tools for the planner's tool list (trusted registry text)."""
    from app.agent import tool_permissions, tool_registry

    tools = []
    for setting in tool_permissions.effective_tools(db, profile):
        if not _field(setting, "enabled") or _field(setting, "available") is False:
            continue
        try:
            tool = tool_registry.get(_field(setting, "name"))
        except ToolNotFoundError:
            continue
        if source == "public" and not tool.public_safe:
            continue
        tools.append(
            {"name": tool.name, "risk": tool.risk.value, "description": tool.description, "input_schema": tool.input_schema}
        )
    return tools


# --- Entry point ------------------------------------------------------------------------


def run_execution(execution_id: uuid.UUID) -> None:
    """Run (or resume) one queued execution in its own session."""
    with runner.SessionLocal() as db:
        execution = db.get(AgentExecution, execution_id)
        if execution is None or execution.status != "queued":
            return
        AgentRun(db, execution).run()


def _now() -> datetime:
    return datetime.now(UTC)


class AgentRun:
    def __init__(self, db: Session, execution: AgentExecution) -> None:
        settings = get_settings()
        self.db = db
        self.ex = execution
        self.clone = db.get(CloneProfile, execution.clone_id)
        self.profile = db.get(AgentProfile, execution.agent_id)
        self.conversation = db.get(Conversation, execution.conversation_id) if execution.conversation_id else None
        owner_id = self.clone.owner_id if self.clone else None
        acting_id = self.conversation.user_id if self.conversation else owner_id
        self.acting_user = db.get(User, acting_id) if acting_id else None
        max_steps = self.profile.max_steps if self.profile else 1
        max_time = self.profile.max_execution_time_seconds if self.profile else 1
        self.max_steps = max(1, min(max_steps, settings.agent_max_steps))
        self.max_tool_calls = max(0, settings.agent_max_tool_calls)
        self.time_limit = max(1, min(max_time, settings.agent_max_execution_time_seconds))
        self.max_chars = max(2000, settings.agent_max_context_chars)
        self.retries = max(0, settings.agent_max_tool_retries)
        self.is_owner = execution.source != "public" and owner_id is not None and execution.user_id == owner_id
        self.llm = factory.get_llm_provider()
        self.started = _clock()
        self.state = run_state.RunState(execution_id=execution.id)
        self.next_step = 1
        self.tools: list[dict] = []

    # --- time, cancellation ------------------------------------------------------------

    def elapsed(self) -> float:
        return self.state.elapsed_before + (_clock() - self.started)

    def remaining(self) -> float:
        return self.time_limit - self.elapsed()

    def _checkpoint(self) -> None:
        """Before every planner/tool call: stop on cancel or when time is up."""
        self.db.refresh(self.ex, attribute_names=["cancel_requested"])
        if self.ex.cancel_requested:
            raise _Stop("cancelled", CANCELLED)
        if self.remaining() <= 0:
            raise _Stop("timeout", TIMEOUT)

    def _run_llm(self, coroutine):
        try:
            return runner.run_async(coroutine, self.remaining())
        except TimeoutError as exc:
            raise _Stop("timeout", TIMEOUT) from exc

    # --- records -----------------------------------------------------------------------

    def _security(self, event: str, **details: Any) -> None:
        monitoring.security(event, "low", user_id=self.ex.user_id, details={"execution_id": self.ex.id, **details})

    def _step(
        self,
        step_type: str,
        status: str,
        *,
        tool_name: str | None = None,
        inputs: dict | None = None,
        outputs: dict | None = None,
        duration_ms: int | None = None,
    ) -> AgentStep:
        step = AgentStep(
            execution_id=self.ex.id,
            step_number=self.next_step,
            step_type=step_type,
            tool_name=(tool_name or None) and tool_name[:60],
            status=status,
            input_metadata=safety.redact_data(inputs or {}),
            output_metadata=safety.redact_data(outputs or {}),
            duration_ms=duration_ms,
            created_at=_now(),
        )
        self.next_step += 1
        self.ex.total_steps = step.step_number
        self.db.add(step)
        self.db.commit()
        return step

    def _no_progress_check(self) -> None:
        if self.state.no_progress >= run_state.MAX_NO_PROGRESS:
            raise _Stop("failed", NO_PROGRESS)

    # --- the run -----------------------------------------------------------------------

    def run(self) -> None:
        ex = self.ex
        try:
            if self.clone is None or self.profile is None:
                raise _Stop("failed", UNAVAILABLE)
            steps = list(self.db.scalars(select(AgentStep).where(AgentStep.execution_id == ex.id)))
            self.state = run_state.load(ex, steps)
            self.next_step = max((s.step_number for s in steps), default=0) + 1
            if ex.started_at is None:
                ex.started_at = _now()
                self._security("agent_started", source=ex.source)
            ex.status = "planning"
            pending = ex.pending_action
            ex.pending_action = None  # single use: cleared before anything runs
            self.db.commit()
            self.tools = available_tools(self.db, self.profile, source=ex.source)
            if pending and pending.get("state") == "approved":
                self._run_approved(pending)
            elif pending and pending.get("state") == "rejected":
                self.state.observe(
                    Observation(
                        int(pending.get("_step") or 0),
                        "user",
                        f"The user declined the action '{pending.get('title')}' ({pending.get('input_preview')}). "
                        "Don't request it again; continue without it or give your final answer.",
                        ok=False,
                    )
                )
            self._loop()
        except _Paused:
            return
        except _Stop as stop:
            self._end(stop.status, stop.message)
        except planner.PlannerOutputError:
            self._end("failed", PLANNER_FAILED)
        except Exception:  # noqa: BLE001 - the run must always end in a final status
            logger.exception("Agent execution %s failed", ex.id)
            self._end("failed", FAILED)

    def _loop(self) -> None:
        system = planner_system_prompt(
            clone_name=self.clone.name,
            agent_name=self.profile.name,
            tools=self.tools,
            can_propose_memory=self.is_owner,
        )
        while True:
            self._checkpoint()
            if self.state.decisions >= self.max_steps:
                raise _Stop("failed", STEP_LIMIT)
            self.ex.status = "planning"
            self.db.commit()
            message = context.planner_message(
                self.ex.goal,
                self.state,
                max_steps=self.max_steps,
                max_tool_calls=self.max_tool_calls,
                max_chars=self.max_chars,
            )
            decision = planner.decide(system, message, self._run_llm)
            self._checkpoint()
            self.state.decisions += 1
            self.ex.current_step = self.state.decisions
            if decision.action == "final":
                self._finish(decision)
                return
            if decision.action == "propose_memory":
                self._propose_memory(decision)
                continue
            self._tool(decision)

    # --- tools -------------------------------------------------------------------------

    def _allowed(self, name: str, summary: str) -> tuple[Tool, bool] | None:
        try:
            return check_tool_call(self.db, self.profile, name, source=self.ex.source)
        except (ToolNotFoundError, ToolNotAllowedError) as exc:
            reason = "unknown" if isinstance(exc, ToolNotFoundError) else "not_allowed"
            step = self._step(
                "tool",
                "failed",
                tool_name=name,
                inputs={"summary": summary},
                outputs={"summary": f"Tool not available: {safety.short(name, 60)}", "error": reason},
            )
            self._security("tool_failed", tool=name[:60], status=reason)
            self.state.record_result(False, False)
            self.state.observe(
                Observation(
                    step.step_number,
                    "system",
                    f"The tool '{safety.short(name, 60)}' is not available to this agent. Use only the listed tools.",
                    ok=False,
                )
            )
            self._no_progress_check()
            return None

    def _validated(self, tool: Tool, arguments: dict, summary: str) -> dict | None:
        try:
            return tool.validate(dict(arguments))
        except ToolInputError as exc:
            message = safety.short(str(exc), 200) or "Invalid arguments."
            step = self._step(
                "tool",
                "failed",
                tool_name=tool.name,
                inputs={"summary": summary, "arg_keys": sorted(arguments)[:20]},
                outputs={"summary": f"Invalid input for {tool.title}", "error": message},
            )
            self.state.record_result(False, False)
            self.state.observe(
                Observation(step.step_number, f"tool:{tool.name}", f"Invalid arguments: {message}", ok=False)
            )
            self._no_progress_check()
            return None

    def _tool(self, decision: PlannerDecision) -> None:
        name = decision.tool or ""
        allowed = self._allowed(name, decision.summary)
        if allowed is None:
            return
        tool, needs_confirmation = allowed
        arguments = self._validated(tool, decision.arguments, decision.summary)
        if arguments is None:
            return
        signature = run_state.signature(tool.name, arguments)
        if self.state.count_request(signature) > run_state.MAX_SAME_CALL:
            raise _Stop("failed", NO_PROGRESS)
        if signature in self.state.rejected:
            step = self._step(
                "tool",
                "skipped",
                tool_name=tool.name,
                inputs={"signature": signature, "summary": decision.summary},
                outputs={"summary": f"Skipped {tool.title}: you declined this action"},
            )
            self.state.observe(
                Observation(step.step_number, "user", "The user already declined this exact action. Don't request it again.", ok=False)
            )
            return
        if self.state.tool_calls >= self.max_tool_calls:
            raise _Stop("failed", TOOL_LIMIT)
        if needs_confirmation:
            self._pause(tool, arguments, signature, decision.summary)
        self._execute(tool, arguments, signature, decision.summary)

    def _pause(self, tool: Tool, arguments: dict, signature: str, summary: str) -> None:
        preview = safety.input_preview(arguments)
        step = self._step(
            "confirmation",
            "waiting",
            tool_name=tool.name,
            inputs={"action_signature": signature, "input_preview": preview, "risk": tool.risk.value},
            outputs={"summary": f"Waiting for your confirmation to use {tool.title}"},
        )
        self.ex.pending_action = {
            "action_id": uuid.uuid4().hex,
            "tool": tool.name,
            "title": tool.title,
            "reason": safety.short(summary, 200) or f"The agent wants to use {tool.title}.",
            "risk": tool.risk.value,
            "input_preview": preview,
            # Internal (never returned by the API): what exactly runs on approval.
            "_arguments": arguments,
            "_signature": signature,
            "_summary": safety.short(summary, 200),
            "_step": step.step_number,
            "_elapsed": round(self.elapsed(), 3),
        }
        self.ex.status = "waiting_confirmation"
        self.db.commit()
        self._security("confirmation_requested", tool=tool.name, status="waiting")
        raise _Paused

    def _run_approved(self, pending: dict) -> None:
        """Run exactly the call the user approved (re-checked: permissions may have changed)."""
        self._checkpoint()
        name = str(pending.get("tool") or "")
        summary = str(pending.get("_summary") or "")
        allowed = self._allowed(name, summary)
        if allowed is None:
            return
        tool, _ = allowed
        arguments = self._validated(tool, pending.get("_arguments") or {}, summary)
        if arguments is None:
            return
        signature = run_state.signature(tool.name, arguments)
        self.state.count_request(signature)
        if self.state.tool_calls >= self.max_tool_calls:
            raise _Stop("failed", TOOL_LIMIT)
        self._execute(tool, arguments, signature, summary)

    def _execute(self, tool: Tool, arguments: dict, signature: str, summary: str) -> None:
        self._checkpoint()
        ex = self.ex
        ex.status = "running"
        self.state.tool_calls += 1
        ex.tool_calls = self.state.tool_calls
        step = self._step(
            "tool",
            "running",
            tool_name=tool.name,
            inputs={
                "signature": signature,
                "summary": summary,
                "input_preview": safety.input_preview(arguments),
                "risk": tool.risk.value,
            },
        )
        self._security("tool_called", tool=tool.name, status="started")
        ctx = ToolContext(
            db=self.db,
            clone=self.clone,
            acting_user=self.acting_user,
            execution_id=ex.id,
            source=ex.source,  # type: ignore[arg-type]
            is_owner=self.is_owner,
            conversation_id=ex.conversation_id,
        )

        def record_attempt(attempt: int, result, duration_ms: int) -> None:
            monitoring.usage(
                "AGENT_TOOL_CALL",
                provider=tool.name,
                status="success" if result.ok else "failed",
                user_id=ex.user_id,
                clone_id=ex.clone_id,
                organization_id=self.clone.organization_id,
                api_key_id=ex.api_key_id,
                duration_ms=duration_ms,
            )

        outcome = executor.run_tool(
            tool, ctx, arguments, remaining=self.remaining, retries=self.retries, on_attempt=record_attempt
        )
        result = outcome.result
        limit = context.per_observation_limit(self.max_chars)
        data_text = context.observation_text(result.data, limit) if result.ok else ""
        error = safety.short(result.error, 200) if not result.ok else None
        default_summary = f"Used {tool.title}" if result.ok else f"{tool.title} failed"
        step.status = "succeeded" if result.ok else "failed"
        step.duration_ms = outcome.duration_ms
        step.output_metadata = safety.redact_data(
            {
                "summary": safety.short(result.summary, 200) or default_summary,
                "ok": result.ok,
                "empty": bool(result.empty),
                "size": len(data_text),
                "attempts": outcome.attempts,
                **({"error": error} if error else {}),
            }
        )
        self.db.commit()
        if not result.ok:
            self._security("tool_failed", tool=tool.name, status="timeout" if outcome.timed_out else "failed")
        self.state.record_result(result.ok, bool(result.empty))
        if result.ok:
            text = data_text or safety.short(result.summary, 500) or "(no data)"
            if result.empty:
                text = f"(no results) {text}"
        else:
            text = f"Error: {error or executor.TOOL_FAILED}"
        self.state.observe(Observation(step.step_number, f"tool:{tool.name}", text, ok=result.ok))
        if self.remaining() <= 0:
            raise _Stop("timeout", TIMEOUT)
        self._no_progress_check()

    # --- memory suggestions --------------------------------------------------------------

    def _propose_memory(self, decision: PlannerDecision) -> None:
        memory = decision.memory or {}
        content = " ".join(str(memory.get("content") or "").split())[:1000]
        memory_type = str(memory.get("memory_type") or "fact")
        if not self.is_owner:
            status, summary, note = "skipped", "Memory suggestions aren't available in this run", (
                "Memory suggestions aren't available in this run. Continue without it."
            )
        elif safety.looks_sensitive(content):
            status, summary, note = "rejected", "A memory suggestion was refused because it looked like a secret", (
                "That memory suggestion was refused: secrets and credentials are never stored. Continue."
            )
        elif self.ex.memory_proposal:
            status, summary, note = "skipped", "Only one memory suggestion per run", (
                "A memory suggestion is already waiting for the user. Continue."
            )
        else:
            self.ex.memory_proposal = {
                "proposal_id": uuid.uuid4().hex,
                "content": safety.redact(content),
                "memory_type": memory_type,
            }
            status, summary, note = "waiting", "Suggested a memory for you to review", (
                "The memory suggestion was shown to the user; it is saved only if they approve. Continue with the goal."
            )
        step = self._step(
            "memory_proposal",
            status,
            inputs={"summary": decision.summary, "memory_type": memory_type, "size": len(content)},
            outputs={"summary": summary},
        )
        self.state.observe(Observation(step.step_number, "system", note, ok=status == "waiting"))

    # --- the end -----------------------------------------------------------------------

    def _finish(self, decision: PlannerDecision) -> None:
        ex = self.ex
        draft = safety.redact(decision.answer or "")
        started = _clock()
        text = ""
        if self.remaining() > 0:
            system = build_clone_system_prompt(
                self.clone, self.clone.owner.full_name if self.is_owner and self.clone.owner else None
            ) + FINAL_ADDENDUM
            reference = context.final_context(self.state.observations, draft, max_chars=self.max_chars)
            try:
                text = self._run_llm(self.llm.generate_response(system, ex.goal, context=reference)) or ""
            except _Stop:
                text = ""  # out of time: the planner's draft is the answer
            except Exception as exc:  # noqa: BLE001 - fall back to the draft
                logger.warning("Agent final answer failed for %s: %s", ex.id, type(exc).__name__)
                text = ""
        answer = safety.redact(text).strip() or draft
        latency = int((_clock() - started) * 1000)
        message = self._save_answer(answer, latency)
        self._step(
            "final",
            "succeeded",
            inputs={"summary": decision.summary},
            outputs={"summary": "Final answer ready", "size": len(answer)},
            duration_ms=latency,
        )
        ex.final_message_id = message.id if message is not None else None
        ex.result_summary = answer[:4000]
        self._end("completed", None)

    def _save_answer(self, answer: str, latency_ms: int):
        if self.ex.source == "public" or self.acting_user is None:
            return None
        conversation = self.conversation
        if conversation is None:
            conversation = conversation_service.get_or_create(
                self.db, self.clone, self.acting_user, None, source="api" if self.ex.source == "api" else "app"
            )
            conversation_service.add_message(self.db, conversation, "user", self.ex.goal)
            self.ex.conversation_id = conversation.id
        return conversation_service.add_message(
            self.db, conversation, "assistant", answer, model_name=self.llm.model_name, latency_ms=latency_ms
        )

    def _end(self, status: str, message: str | None) -> None:
        db, ex = self.db, self.ex
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - drop anything half-written by a failed step
            db.rollback()
        db.refresh(ex)
        if ex.status in FINAL_STATUSES:
            return
        if status != "completed":
            step_status = "skipped" if status == "cancelled" else "failed"
            try:
                last = db.scalar(
                    select(AgentStep.step_number)
                    .where(AgentStep.execution_id == ex.id)
                    .order_by(AgentStep.step_number.desc())
                    .limit(1)
                )
                self.next_step = (last or 0) + 1
                self._step("error", step_status, outputs={"summary": message or FAILED, "status": status})
            except Exception:  # noqa: BLE001
                db.rollback()
                db.refresh(ex)
        ex.status = status
        ex.error_message = safety.short(message, 500) if message else None
        ex.pending_action = None
        ex.completed_at = _now()
        db.commit()
        run_state.forget(ex.id)
        usage_status = {"completed": "success"}.get(status, status)
        duration_ms = int(self.elapsed() * 1000)
        monitoring.usage(
            "AGENT_EXECUTION",
            provider=self.llm.name,
            status=usage_status,
            user_id=ex.user_id,
            clone_id=ex.clone_id,
            organization_id=self.clone.organization_id if self.clone else None,
            api_key_id=ex.api_key_id,
            duration_ms=duration_ms,
            output_units=self.state.decisions,
        )
        if status in ("failed", "timeout"):
            monitoring.usage(
                "AGENT_ERROR",
                provider=self.llm.name,
                status=status,
                user_id=ex.user_id,
                clone_id=ex.clone_id,
                organization_id=self.clone.organization_id if self.clone else None,
                api_key_id=ex.api_key_id,
            )
        event = {"completed": "agent_completed", "cancelled": "agent_cancelled", "timeout": "agent_timeout"}
        self._security(event.get(status, "agent_failed"), status=status, steps=self.state.decisions)
