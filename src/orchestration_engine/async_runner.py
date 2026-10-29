"""
Asynchronous workflow coordinator using Python standard library asyncio.

Allows running workflows with native async/await task runners, scaling to
thousands of concurrent I/O-bound tasks with zero external runtime dependencies.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from orchestration_engine.errors import PersistenceError, WorkflowValidationError
from orchestration_engine.executor import execute_task
from orchestration_engine.models import (
    Hooks,
    Task,
    TaskResult,
    TaskState,
    Workflow,
    WorkflowStatus,
)
from orchestration_engine.persistence import (
    _migrate_database,
    get_connection,
    get_task_outputs,
)
from orchestration_engine.runner import (
    _handle_task_failure,
    _handle_task_success,
    _safe_call_hook,
    _serialize_workflow,
)
from orchestration_engine.scheduler import schedule_once
from orchestration_engine.status import get_workflow_status
from orchestration_engine.transitions import mirror_task_states
from orchestration_engine.validation import get_workflow_validation_error

logger = logging.getLogger("orchestration_engine.async")

AsyncTaskRunnerCallable = Callable[
    [Task],
    bool | TaskResult | Coroutine[Any, Any, bool | TaskResult],
]


async def _invoke_runner(
    task: Task,
    task_runner: AsyncTaskRunnerCallable,
) -> bool | TaskResult:
    """Execute task_runner, handling both coroutine functions and sync functions."""
    if inspect.iscoroutinefunction(task_runner):
        result = await task_runner(task)
    else:
        # Check if calling task_runner returns a coroutine object
        maybe_coro = task_runner(task)
        if inspect.isawaitable(maybe_coro):
            result = await maybe_coro
        else:
            result = maybe_coro

    if isinstance(result, TaskResult):
        return result
    return bool(result)


async def run_workflow_async(
    workflow: Workflow,
    task_runner: AsyncTaskRunnerCallable,
    *,
    task_states: dict[str, TaskState] | None = None,
    conn: sqlite3.Connection | None = None,
    db_path: str | None = None,
    time_source: Callable[[], float] = time.time,
    run_id: str | None = None,
    max_concurrency: int = 100,
    hooks: Hooks | None = None,
) -> WorkflowStatus:
    """
    Asynchronously run a Workflow to completion inside an asyncio event loop.

    Repeatedly schedules ready tasks and executes them concurrently using
    asyncio tasks up to max_concurrency. Supports both 'async def' and sync
    task_runner callables. Non-blocking timeouts are enforced via asyncio.wait_for.

    Args:
        workflow: The Workflow DAG definition.
        task_runner: Async or sync callable accepting a Task and returning bool or TaskResult.
        task_states: Optional in-memory mapping of task_id to TaskState.
        conn: Optional SQLite connection. If omitted, opens/creates one using db_path.
        db_path: Path to SQLite DB if conn is not provided (defaults to :memory:).
        time_source: Wall-clock time callable (defaults to time.time).
        run_id: Optional custom run identifier.
        max_concurrency: Maximum number of concurrent tasks (default 100).
        hooks: Optional lifecycle callbacks.

    Returns:
        The final WorkflowStatus (SUCCEEDED or FAILED).
    """
    validation_error = get_workflow_validation_error(workflow)
    if validation_error:
        raise WorkflowValidationError(f"workflow is invalid: {validation_error}")

    if (
        isinstance(max_concurrency, bool)
        or not isinstance(max_concurrency, int)
        or max_concurrency < 1
    ):
        raise WorkflowValidationError("max_concurrency must be an integer >= 1")

    close_conn_at_exit = False
    if conn is None:
        target_path = db_path if db_path is not None else ":memory:"
        conn = get_connection(target_path)
        close_conn_at_exit = True

    states_dict = task_states if task_states is not None else {}
    actual_run_id = run_id if run_id is not None else uuid.uuid4().hex
    for task in workflow.tasks:
        task._run_id = actual_run_id
    mirror_task_states(workflow.tasks, states_dict)

    _migrate_database(conn)
    started_at = time_source()
    definition_json = _serialize_workflow(workflow)

    try:
        conn.execute(
            """
            INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json)
            VALUES (?, ?, ?, NULL, 'running', ?)
            ON CONFLICT(run_id) DO UPDATE SET status = 'running', finished_at = NULL
            """,
            (actual_run_id, workflow.workflow_id, started_at, definition_json),
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(
            "Persistence failure recording run start: %s",
            e,
            extra={
                "workflow_id": workflow.workflow_id,
                "run_id": actual_run_id,
                "task_id": None,
                "old_state": None,
                "new_state": None,
                "attempt": None,
            },
        )
        if close_conn_at_exit:
            conn.close()
        raise PersistenceError(f"Failed to record run start: {e}") from e

    run_outputs = get_task_outputs(conn, actual_run_id)
    in_flight: dict[asyncio.Task[Any], tuple[Task, float]] = {}

    try:
        while True:
            current_time = time_source()
            schedule_once(workflow, states_dict, current_time, conn)

            in_flight_ids = {t.task_id for t, _ in in_flight.values()}
            dispatchable = [
                t
                for t in workflow.tasks
                if t.state == TaskState.READY and t.task_id not in in_flight_ids
            ]
            slots = max_concurrency - len(in_flight)
            to_dispatch = dispatchable[: max(0, slots)]

            for task in to_dispatch:
                dep_inputs = {
                    dep: run_outputs[dep]
                    for dep in task.dependencies
                    if dep in run_outputs
                }
                task.inputs = {**task.inputs, **dep_inputs}
                execute_task(task, conn, current_time)
                if hooks:
                    _safe_call_hook(hooks.on_task_start, task)

                start_timestamp = current_time

                async def _worker(t: Task) -> tuple[bool, Any, str | None]:
                    try:
                        if t.timeout_seconds is not None and t.timeout_seconds > 0:
                            ret = await asyncio.wait_for(
                                _invoke_runner(t, task_runner),
                                timeout=t.timeout_seconds,
                            )
                        else:
                            ret = await _invoke_runner(t, task_runner)

                        if isinstance(ret, TaskResult):
                            return ret.ok, ret.output, ret.error
                        else:
                            return bool(ret), None, None
                    except TimeoutError:
                        return False, None, f"TimeoutError: task exceeded {t.timeout_seconds}s"
                    except BaseException as exc:
                        return False, None, f"{type(exc).__name__}: {exc}"

                async_task = asyncio.create_task(_worker(task))
                in_flight[async_task] = (task, start_timestamp)

            if not in_flight:
                # Check if tasks are waiting for retry
                retry_tasks = [
                    t
                    for t in workflow.tasks
                    if t.state == TaskState.RETRY_WAIT and t.next_retry_at is not None
                ]
                if retry_tasks:
                    earliest_retry = min(
                        t.next_retry_at
                        for t in retry_tasks
                        if t.next_retry_at is not None
                    )
                    wait_sec = max(0.01, earliest_retry - current_time)
                    await asyncio.sleep(min(wait_sec, 0.05))
                    continue
                break

            # Wait for at least one in-flight task to complete
            done, _ = await asyncio.wait(
                in_flight.keys(),
                return_when=asyncio.FIRST_COMPLETED,
            )

            finish_time = time_source()
            for done_fut in done:
                task, _ = in_flight.pop(done_fut)
                ok, output, error = done_fut.result()

                if ok:
                    _handle_task_success(
                        task,
                        output,
                        actual_run_id,
                        conn,
                        finish_time,
                        states_dict,
                        run_outputs,
                        hooks=hooks,
                    )
                else:
                    _handle_task_failure(
                        task,
                        error,
                        actual_run_id,
                        conn,
                        finish_time,
                        states_dict,
                        hooks=hooks,
                    )

        # Finalize run
        final_status = get_workflow_status(workflow)
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (time_source(), final_status.value, actual_run_id),
        )
        conn.commit()

        if hooks:
            _safe_call_hook(hooks.on_workflow_done, workflow, final_status)

        return final_status

    finally:
        # Cancel any stray tasks in flight
        for async_task in in_flight:
            async_task.cancel()
        if close_conn_at_exit:
            conn.close()
