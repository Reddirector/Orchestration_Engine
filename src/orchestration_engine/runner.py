import concurrent.futures
import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal

from orchestration_engine.errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowValidationError,
)
from orchestration_engine.executor import complete_task, execute_task, fail_task
from orchestration_engine.models import Task, TaskState, Workflow, WorkflowStatus
from orchestration_engine.persistence import _migrate_database
from orchestration_engine.scheduler import schedule_once
from orchestration_engine.status import get_workflow_status
from orchestration_engine.transitions import mirror_task_states
from orchestration_engine.validation import get_workflow_validation_error

ExecutorType = Literal["thread"]


def _serialize_workflow(workflow: Workflow) -> str:
    data = {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "description": workflow.description,
        "default_timeout_seconds": workflow.default_timeout_seconds,
        "tasks": [
            {
                "task_id": task.task_id,
                "name": task.name,
                "description": task.description,
                "dependencies": list(task.dependencies),
                "retry_policy": {
                    "max_attempts": task.retry_policy.max_attempts,
                    "delay_seconds": task.retry_policy.delay_seconds,
                },
                "timeout_seconds": task.timeout_seconds,
            }
            for task in workflow.tasks
        ],
    }
    return json.dumps(data)


def run_workflow(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: Callable[[Task], bool],
    conn: sqlite3.Connection,
    sleep: Callable[[float], None] = time.sleep,
    *,
    run_id: str | None = None,
    max_concurrency: int = 1,
    executor: ExecutorType = "thread",
) -> str:
    """
    Run a Workflow to completion, executing tasks as their dependencies clear.

    Repeatedly schedules and executes ready tasks until none remain ready.
    Tasks are executed concurrently up to max_concurrency using the chosen
    executor ("thread" or "process"). An internal "_inline" executor is available
    for deterministic virtual-clock tests.

    For each task, task_runner is called with the Task and must return True
    on success or False on failure; failures are retried according to the
    task's retry_policy. A task_runner that raises, or that exceeds the
    task's timeout_seconds, is treated as a failure. Note that Python threads
    cannot be killed: with executor="thread", a timed-out callable keeps
    running in the background while the engine moves on. With executor="process",
    timed-out child processes are terminated and killed.

    Mutates the Task objects inside workflow in place and persists state
    transitions via conn using a single-writer coordinator model.
    Raises WorkflowValidationError if the workflow or parameters fail validation.

    Returns the run_id (either passed in or freshly generated).
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

    if executor != "thread":
        raise WorkflowValidationError(
            f"invalid executor {executor!r}, must be 'thread'"
        )

    actual_run_id = run_id if run_id is not None else uuid.uuid4().hex
    for task in workflow.tasks:
        task._run_id = actual_run_id
    mirror_task_states(workflow.tasks, task_states)

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
        raise PersistenceError(f"Failed to record run start: {e}") from e

    _run_coordinator_thread(
        workflow=workflow,
        task_states=task_states,
        time_source=time_source,
        task_runner=task_runner,
        conn=conn,
        sleep=sleep,
        max_concurrency=max_concurrency,
    )

    finished_at = time_source()
    final_status = get_workflow_status(workflow).value
    try:
        conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (finished_at, final_status, actual_run_id),
        )
        conn.commit()
    except sqlite3.Error as e:
        raise PersistenceError(f"Failed to record run completion: {e}") from e

    mirror_task_states(workflow.tasks, task_states)
    return actual_run_id


def _run_coordinator_thread(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: Callable[[Task], bool],
    conn: sqlite3.Connection,
    sleep: Callable[[float], None],
    max_concurrency: int,
) -> None:
    pool = ThreadPoolExecutor(max_workers=max_concurrency)
    in_flight: dict[Future[bool], tuple[Task, float, float | None]] = {}

    try:
        while True:
            current_time = time_source()
            schedule_once(workflow, task_states, current_time, conn)

            in_flight_ids = {t.task_id for t, _, _ in in_flight.values()}
            dispatchable = [
                t
                for t in workflow.tasks
                if t.state == TaskState.READY and t.task_id not in in_flight_ids
            ]
            slots = max_concurrency - len(in_flight)
            to_dispatch = dispatchable[: max(0, slots)]

            for task in to_dispatch:
                execute_task(task, conn, current_time)
                mono_start = time.monotonic()
                mono_deadline = (
                    mono_start + task.timeout_seconds
                    if task.timeout_seconds is not None
                    else None
                )
                fut = pool.submit(task_runner, task)
                in_flight[fut] = (task, mono_start, mono_deadline)

            if not in_flight:
                retry_waits = [
                    t.next_retry_at
                    for t in workflow.tasks
                    if t.state == TaskState.RETRY_WAIT and t.next_retry_at is not None
                ]
                if not retry_waits:
                    break
                wait_time = max(0.0, min(retry_waits) - current_time)
                sleep(wait_time)
                continue

            # Compute timeout to nearest deadline or retry_wait
            mono_now = time.monotonic()
            deadlines = [
                max(0.0, dl - mono_now)
                for _, _, dl in in_flight.values()
                if dl is not None
            ]
            wait_candidates = list(deadlines)
            if len(in_flight) < max_concurrency:
                retry_cands = [
                    max(0.0, t.next_retry_at - current_time)
                    for t in workflow.tasks
                    if t.state == TaskState.RETRY_WAIT and t.next_retry_at is not None
                ]
                wait_candidates.extend(retry_cands)

            wait_timeout = min(wait_candidates) if wait_candidates else None

            done, _ = concurrent.futures.wait(
                in_flight.keys(),
                timeout=wait_timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            finish_time = time_source()
            for fut in done:
                task, _, _ = in_flight.pop(fut)
                try:
                    exc = fut.exception()
                    if exc is not None:
                        task.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                        fail_task(task, finish_time, conn, task_states)
                    else:
                        ok = fut.result()
                        if ok:
                            complete_task(task, conn, finish_time, task_states)
                        else:
                            fail_task(task, finish_time, conn, task_states)
                except Exception as exc:
                    task.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                    fail_task(task, finish_time, conn, task_states)

            # Check timeouts on remaining in-flight tasks
            mono_now = time.monotonic()
            for fut, (task, _, dl) in list(in_flight.items()):
                if dl is not None and mono_now >= dl:
                    del in_flight[fut]
                    task.last_error = f"timeout after {task.timeout_seconds}s"
                    fail_time = time_source()
                    fail_task(task, fail_time, conn, task_states)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def resume_run(
    conn: sqlite3.Connection,
    run_id: str,
    task_runner: Callable[[Task], bool],
    time_source: Callable[[], float],
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_concurrency: int = 1,
    executor: ExecutorType = "thread",
) -> WorkflowStatus:
    """
    Resume an interrupted or pending workflow run.

    Rebuilds the Workflow from definition_json stored in the database,
    restores each task's latest state, attempt_count, and next_retry_at.
    Never re-executes SUCCEEDED tasks. Any task found in RUNNING state
    is treated as an interrupted failure with last_error set to
    "interrupted: process exited while running", and retried/failed per policy.
    Resuming an already finished run returns its status immediately.
    """
    _migrate_database(conn)
    cursor = conn.execute(
        "SELECT status, definition_json FROM runs WHERE run_id = ?",
        (run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise OrchestrationError(f"Run {run_id!r} not found in database")

    status_str, definition_json = row
    if status_str in (WorkflowStatus.SUCCEEDED.value, WorkflowStatus.FAILED.value):
        return WorkflowStatus(status_str)

    from orchestration_engine.loader import load_workflow_from_json

    workflow = load_workflow_from_json(json.loads(definition_json))

    cursor = conn.execute(
        """
        SELECT task_id, new_state, attempt_count, next_retry_at, error
        FROM task_events
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    )
    events_by_task: dict[str, tuple[str, int, float | None, str | None]] = {}
    for task_id, new_state, attempt_count, next_retry_at, error in cursor.fetchall():
        events_by_task[task_id] = (new_state, attempt_count, next_retry_at, error)

    task_states: dict[str, TaskState] = {}
    for task in workflow.tasks:
        task._run_id = run_id
        if task.task_id in events_by_task:
            new_state, attempt_count, next_retry_at, error = events_by_task[task.task_id]
            task.state = TaskState(new_state)
            task.attempt_count = attempt_count
            task.next_retry_at = next_retry_at
            task.last_error = error
        task_states[task.task_id] = task.state

    current_time = time_source()
    for task in workflow.tasks:
        if task.state == TaskState.RUNNING:
            task.last_error = "interrupted: process exited while running"
            fail_task(task, current_time, conn, task_states)

    run_workflow(
        workflow,
        task_states,
        time_source,
        task_runner,
        conn,
        sleep=sleep,
        run_id=run_id,
        max_concurrency=max_concurrency,
        executor=executor,
    )

    return get_workflow_status(workflow)
