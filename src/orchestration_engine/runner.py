import concurrent.futures
import json
import logging
import multiprocessing
import multiprocessing.connection
import pickle
import sqlite3
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Literal

from orchestration_engine.errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowValidationError,
)
from orchestration_engine.executor import complete_task, execute_task, fail_task
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
    get_task_outputs,
    save_task_output,
)
from orchestration_engine.scheduler import schedule_once
from orchestration_engine.status import get_workflow_status
from orchestration_engine.transitions import mirror_task_states
from orchestration_engine.validation import get_workflow_validation_error

logger = logging.getLogger("orchestration_engine")

ExecutorType = Literal["thread", "process", "_inline"]
TaskRunnerCallable = Callable[[Task], bool | TaskResult]


def _process_task_target(
    task: Task,
    task_runner: TaskRunnerCallable,
    pipe: Any,
) -> None:
    try:
        ret = task_runner(task)
        if isinstance(ret, TaskResult):
            pipe.send((ret.ok, ret.output, ret.error))
        else:
            pipe.send((bool(ret), None, None))
    except BaseException as exc:
        pipe.send((False, None, f"{type(exc).__name__}: {exc}"[:2000]))
    finally:
        try:
            pipe.close()
        except Exception:
            pass


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


def _safe_call_hook(hook: Any, *args: Any) -> None:
    if hook is None:
        return
    try:
        hook(*args)
    except Exception:
        pass


def _handle_task_success(
    task: Task,
    output: Any,
    run_id: str,
    conn: sqlite3.Connection,
    finish_time: float,
    task_states: dict[str, TaskState],
    run_outputs: dict[str, Any],
    hooks: Hooks | None = None,
) -> None:
    output_json: str | None = None
    if output is not None:
        try:
            output_json = json.dumps(output)
        except Exception as exc:
            task.last_error = f"Task output is not JSON-serializable: {exc}"[:2000]
            save_task_output(conn, run_id, task.task_id, None, task.last_error)
            fail_task(task, finish_time, conn, task_states)
            if hooks:
                if task.state == TaskState.RETRY_WAIT:
                    _safe_call_hook(hooks.on_task_retry, task)
                elif task.state == TaskState.FAILED:
                    _safe_call_hook(hooks.on_task_failed, task)
            return

    save_task_output(conn, run_id, task.task_id, output_json, None)
    run_outputs[task.task_id] = output
    complete_task(task, conn, finish_time, task_states)
    if hooks:
        _safe_call_hook(hooks.on_task_succeeded, task)


def _handle_task_failure(
    task: Task,
    error: str | None,
    run_id: str,
    conn: sqlite3.Connection,
    finish_time: float,
    task_states: dict[str, TaskState],
    hooks: Hooks | None = None,
) -> None:
    if error is not None:
        task.last_error = error[:2000]
    save_task_output(conn, run_id, task.task_id, None, task.last_error)
    fail_task(task, finish_time, conn, task_states)
    if hooks:
        if task.state == TaskState.RETRY_WAIT:
            _safe_call_hook(hooks.on_task_retry, task)
        elif task.state == TaskState.FAILED:
            _safe_call_hook(hooks.on_task_failed, task)


def run_workflow(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: TaskRunnerCallable,
    conn: sqlite3.Connection,
    sleep: Callable[[float], None] = time.sleep,
    *,
    run_id: str | None = None,
    max_concurrency: int = 1,
    executor: ExecutorType = "thread",
    hooks: Hooks | None = None,
) -> str:
    """
    Run a Workflow to completion, executing tasks as their dependencies clear.

    Repeatedly schedules and executes ready tasks until none remain ready.
    Tasks are executed concurrently up to max_concurrency using the chosen
    executor ("thread" or "process"). An internal "_inline" executor is available
    for deterministic virtual-clock tests.

    For each task, task_runner is called with the Task and may return bool
    or TaskResult; failures are retried according to the task's retry_policy.
    Outputs from TaskResult are persisted in SQLite and injected into dependent
    tasks' inputs attribute. Non-JSON-serializable outputs are treated as failed
    attempts.

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

    if executor not in ("thread", "process", "_inline"):
        raise WorkflowValidationError(
            f"invalid executor {executor!r}, must be 'thread' or 'process'"
        )

    if executor == "process":
        try:
            pickle.dumps(task_runner)
        except Exception as exc:
            raise WorkflowValidationError(
                f"task_runner must be picklable for process executor: {exc}"
            ) from exc

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
        raise PersistenceError(f"Failed to record run start: {e}") from e

    run_outputs = get_task_outputs(conn, actual_run_id)

    if executor == "_inline":
        _run_coordinator_inline(
            workflow=workflow,
            task_states=task_states,
            time_source=time_source,
            task_runner=task_runner,
            conn=conn,
            sleep=sleep,
            run_id=actual_run_id,
            run_outputs=run_outputs,
            hooks=hooks,
        )
    elif executor == "process":
        _run_coordinator_process(
            workflow=workflow,
            task_states=task_states,
            time_source=time_source,
            task_runner=task_runner,
            conn=conn,
            sleep=sleep,
            max_concurrency=max_concurrency,
            run_id=actual_run_id,
            run_outputs=run_outputs,
            hooks=hooks,
        )
    else:
        _run_coordinator_thread(
            workflow=workflow,
            task_states=task_states,
            time_source=time_source,
            task_runner=task_runner,
            conn=conn,
            sleep=sleep,
            max_concurrency=max_concurrency,
            run_id=actual_run_id,
            run_outputs=run_outputs,
            hooks=hooks,
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
        logger.error(
            "Persistence failure recording run completion: %s",
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
        raise PersistenceError(f"Failed to record run completion: {e}") from e

    if hooks:
        _safe_call_hook(
            hooks.on_workflow_done, workflow, WorkflowStatus(final_status)
        )

    mirror_task_states(workflow.tasks, task_states)
    return actual_run_id


def _run_coordinator_inline(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: TaskRunnerCallable,
    conn: sqlite3.Connection,
    sleep: Callable[[float], None],
    run_id: str,
    run_outputs: dict[str, Any],
    hooks: Hooks | None = None,
) -> None:
    while True:
        current_time = time_source()
        schedule_once(workflow, task_states, current_time, conn)
        ready_tasks = [t for t in workflow.tasks if t.state == TaskState.READY]
        if not ready_tasks:
            retry_waits = [
                task.next_retry_at
                for task in workflow.tasks
                if task.state == TaskState.RETRY_WAIT and task.next_retry_at is not None
            ]
            if not retry_waits:
                break
            wait_time = max(0.0, min(retry_waits) - current_time)
            sleep(wait_time)
            continue

        for task in ready_tasks:
            dep_inputs = {
                dep: run_outputs[dep]
                for dep in task.dependencies
                if dep in run_outputs
            }
            task.inputs = {**task.inputs, **dep_inputs}
            execute_task(task, conn, current_time)
            if hooks:
                _safe_call_hook(hooks.on_task_start, task)
            try:
                ret = task_runner(task)
            except Exception as exc:
                finish_time = time_source()
                _handle_task_failure(
                    task,
                    f"{type(exc).__name__}: {exc}",
                    run_id,
                    conn,
                    finish_time,
                    task_states,
                    hooks=hooks,
                )
                continue

            finish_time = time_source()
            if isinstance(ret, TaskResult):
                if ret.ok:
                    _handle_task_success(
                        task,
                        ret.output,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        run_outputs,
                        hooks=hooks,
                    )
                else:
                    _handle_task_failure(
                        task,
                        ret.error,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        hooks=hooks,
                    )
            else:
                if ret:
                    _handle_task_success(
                        task,
                        None,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        run_outputs,
                        hooks=hooks,
                    )
                else:
                    _handle_task_failure(
                        task,
                        None,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        hooks=hooks,
                    )


def _run_coordinator_thread(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: TaskRunnerCallable,
    conn: sqlite3.Connection,
    sleep: Callable[[float], None],
    max_concurrency: int,
    run_id: str,
    run_outputs: dict[str, Any],
    hooks: Hooks | None = None,
) -> None:
    pool = ThreadPoolExecutor(max_workers=max_concurrency)
    in_flight: dict[Future[Any], tuple[Task, float, float | None]] = {}

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
                dep_inputs = {
                    dep: run_outputs[dep]
                    for dep in task.dependencies
                    if dep in run_outputs
                }
                task.inputs = {**task.inputs, **dep_inputs}
                execute_task(task, conn, current_time)
                if hooks:
                    _safe_call_hook(hooks.on_task_start, task)
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
                        _handle_task_failure(
                            task,
                            f"{type(exc).__name__}: {exc}",
                            run_id,
                            conn,
                            finish_time,
                            task_states,
                            hooks=hooks,
                        )
                    else:
                        ret = fut.result()
                        if isinstance(ret, TaskResult):
                            if ret.ok:
                                _handle_task_success(
                                    task,
                                    ret.output,
                                    run_id,
                                    conn,
                                    finish_time,
                                    task_states,
                                    run_outputs,
                                    hooks=hooks,
                                )
                            else:
                                _handle_task_failure(
                                    task,
                                    ret.error,
                                    run_id,
                                    conn,
                                    finish_time,
                                    task_states,
                                    hooks=hooks,
                                )
                        else:
                            if ret:
                                _handle_task_success(
                                    task,
                                    None,
                                    run_id,
                                    conn,
                                    finish_time,
                                    task_states,
                                    run_outputs,
                                    hooks=hooks,
                                )
                            else:
                                _handle_task_failure(
                                    task,
                                    None,
                                    run_id,
                                    conn,
                                    finish_time,
                                    task_states,
                                    hooks=hooks,
                                )
                except Exception as exc:
                    _handle_task_failure(
                        task,
                        f"{type(exc).__name__}: {exc}",
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        hooks=hooks,
                    )

            # Check timeouts on remaining in-flight tasks
            mono_now = time.monotonic()
            for fut, (task, _, dl) in list(in_flight.items()):
                if dl is not None and mono_now >= dl:
                    del in_flight[fut]
                    fail_time = time_source()
                    logger.warning(
                        "Task '%s' timed out after %ss (attempt %s)",
                        task.task_id,
                        task.timeout_seconds,
                        task.attempt_count,
                        extra={
                            "workflow_id": task.workflow_id,
                            "run_id": run_id,
                            "task_id": task.task_id,
                            "old_state": task.state.value,
                            "new_state": task.state.value,
                            "attempt": task.attempt_count,
                        },
                    )
                    _handle_task_failure(
                        task,
                        f"timeout after {task.timeout_seconds}s",
                        run_id,
                        conn,
                        fail_time,
                        task_states,
                        hooks=hooks,
                    )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _run_coordinator_process(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: TaskRunnerCallable,
    conn: sqlite3.Connection,
    sleep: Callable[[float], None],
    max_concurrency: int,
    run_id: str,
    run_outputs: dict[str, Any],
    hooks: Hooks | None = None,
) -> None:
    ctx = multiprocessing.get_context("spawn")
    # map task_id -> (task, proc, pipe, mono_start, mono_deadline)
    in_flight: dict[
        str, tuple[Task, Any, Any, float, float | None]
    ] = {}

    try:
        while True:
            current_time = time_source()
            schedule_once(workflow, task_states, current_time, conn)

            dispatchable = [
                t
                for t in workflow.tasks
                if t.state == TaskState.READY and t.task_id not in in_flight
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
                parent_conn, child_conn = ctx.Pipe()
                proc = ctx.Process(
                    target=_process_task_target,
                    args=(task, task_runner, child_conn),
                )
                proc.start()
                child_conn.close()

                mono_start = time.monotonic()
                mono_deadline = (
                    mono_start + task.timeout_seconds
                    if task.timeout_seconds is not None
                    else None
                )
                in_flight[task.task_id] = (
                    task,
                    proc,
                    parent_conn,
                    mono_start,
                    mono_deadline,
                )

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

            mono_now = time.monotonic()
            deadlines = [
                max(0.0, dl - mono_now)
                for _, _, _, _, dl in in_flight.values()
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

            pipe_to_tid = {pipe: tid for tid, (_, _, pipe, _, _) in in_flight.items()}
            ready_pipes: list[Any] = list(
                multiprocessing.connection.wait(
                    list(pipe_to_tid.keys()), timeout=wait_timeout
                )
            )

            finish_time = time_source()
            for pipe in ready_pipes:
                tid = pipe_to_tid[pipe]
                task, proc, _, _, _ = in_flight.pop(tid)
                ok = False
                output: Any = None
                err: str | None = None
                try:
                    if pipe.poll():
                        ok, output, err = pipe.recv()
                    else:
                        proc.join(timeout=0.2)
                        err = f"process exited with exitcode {proc.exitcode}"
                except Exception as exc:
                    err = f"process communication error: {exc}"
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass
                    proc.join(timeout=0.2)
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=0.1)
                        if proc.is_alive():
                            proc.kill()
                            proc.join(timeout=0.1)

                if ok:
                    _handle_task_success(
                        task,
                        output,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        run_outputs,
                        hooks=hooks,
                    )
                else:
                    _handle_task_failure(
                        task,
                        err,
                        run_id,
                        conn,
                        finish_time,
                        task_states,
                        hooks=hooks,
                    )

            # Check timeouts for remaining child processes
            mono_now = time.monotonic()
            for tid, (task, proc, pipe, _, dl) in list(in_flight.items()):
                if dl is not None and mono_now >= dl:
                    del in_flight[tid]
                    try:
                        pipe.close()
                    except Exception:
                        pass
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=0.2)
                        if proc.is_alive():
                            proc.kill()
                            proc.join(timeout=0.1)
                    fail_time = time_source()
                    logger.warning(
                        "Task '%s' timed out after %ss (attempt %s)",
                        task.task_id,
                        task.timeout_seconds,
                        task.attempt_count,
                        extra={
                            "workflow_id": task.workflow_id,
                            "run_id": run_id,
                            "task_id": task.task_id,
                            "old_state": task.state.value,
                            "new_state": task.state.value,
                            "attempt": task.attempt_count,
                        },
                    )
                    _handle_task_failure(
                        task,
                        f"timeout after {task.timeout_seconds}s",
                        run_id,
                        conn,
                        fail_time,
                        task_states,
                        hooks=hooks,
                    )
    finally:
        for _tid, (_task, proc, pipe, _, _) in in_flight.items():
            try:
                pipe.close()
            except Exception:
                pass
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=0.1)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.1)


def resume_run(
    conn: sqlite3.Connection,
    run_id: str,
    task_runner: TaskRunnerCallable,
    time_source: Callable[[], float],
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_concurrency: int = 1,
    executor: ExecutorType = "thread",
    hooks: Hooks | None = None,
) -> WorkflowStatus:
    """
    Resume an interrupted or pending workflow run.

    Rebuilds the Workflow from definition_json stored in the database,
    restores each task's latest state, attempt_count, next_retry_at,
    and task outputs.
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
        hooks=hooks,
    )

    return get_workflow_status(workflow)
