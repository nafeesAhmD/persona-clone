"""Background execution of agent runs (no Redis/Celery: an in-process worker pool, like
avatar video jobs). Executions live in PostgreSQL, so status survives page reloads.

- `submit(execution_id)`: start the run in the background (or right away when INLINE).
  The API request never waits for the run.
- `set_event_loop(loop)`: called at startup with the API's event loop; async provider
  calls from worker threads run on it (shared async clients are bound to that loop).
- `recover_interrupted()`: at startup, mark runs left queued/planning/running as failed
  (a run waiting for confirmation stays waiting: confirming it resumes it).
- Tests set INLINE = True and patch SessionLocal to the test session.
"""

import asyncio
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import update

from app.db.session import SessionLocal  # noqa: F401 - patched in tests

logger = logging.getLogger(__name__)

INLINE = False
WORKERS = 2
INTERRUPTED = "The agent run was interrupted by a server restart. Please run it again."

_app_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _app_loop
    _app_loop = loop


async def _with_timeout(coroutine, timeout: float | None):
    return await asyncio.wait_for(coroutine, timeout) if timeout is not None else await coroutine


def run_async(coroutine, timeout: float | None = None):
    """Run a provider coroutine from a worker thread; raises TimeoutError after `timeout`."""
    if timeout is not None and timeout <= 0:
        coroutine.close()
        raise TimeoutError
    loop = _app_loop
    if loop is not None and loop.is_running():
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not loop:
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            try:
                return future.result(timeout)
            except FutureTimeout as exc:
                future.cancel()
                raise TimeoutError from exc
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_with_timeout(coroutine, timeout))
    # Called from inside a running loop (inline mode in an async route): use a helper thread.
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(_with_timeout(coroutine, timeout))
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            box["error"] = exc

    thread = threading.Thread(target=target, name="agent-async")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


@lru_cache
def _executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="agent-run")


def _run(execution_id: uuid.UUID) -> None:
    from app.agent.agent import run_execution  # avoid an import cycle

    try:
        run_execution(execution_id)
    except Exception:  # noqa: BLE001 - run_execution already records failures
        logger.exception("Agent execution %s crashed", execution_id)


def submit(execution_id: uuid.UUID) -> None:
    if INLINE:
        _run(execution_id)
        return
    _executor().submit(_run, execution_id)


def shutdown() -> None:
    """At app shutdown: drop runs that haven't started (they are marked failed by
    recover_interrupted on the next start) and don't wait for running ones here."""
    if _executor.cache_info().currsize:
        _executor().shutdown(wait=False, cancel_futures=True)
        _executor.cache_clear()


def recover_interrupted() -> int:
    """Mark runs left queued/planning/running by a previous server process as failed."""
    from app.models.agent import AgentExecution

    try:
        with SessionLocal() as db:
            result = db.execute(
                update(AgentExecution)
                .where(AgentExecution.status.in_(("queued", "planning", "running")))
                .values(status="failed", error_message=INTERRUPTED, completed_at=datetime.now(UTC), pending_action=None)
            )
            db.commit()
            if result.rowcount:
                logger.info("Marked %d interrupted agent runs as failed", result.rowcount)
            return result.rowcount
    except Exception as exc:  # noqa: BLE001 - startup must not fail on this
        logger.warning("Could not recover agent runs: %s", exc)
        return 0
