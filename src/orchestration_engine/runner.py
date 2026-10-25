import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from orchestration_engine.executor import complete_task, execute_task, fail_task
from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.scheduler import schedule_once
from orchestration_engine.transitions import transition_task
from orchestration_engine.validation import validate_workflow


def run_workflow(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: Callable[[Task], bool],
    conn: sqlite3.Connection,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """
    Run a Workflow to completion, executing tasks as their dependencies clear.

    Repeatedly schedules and executes ready tasks until none remain ready.
    For each task, task_runner is called with the Task and must return True
    on success or False on failure; failures are retried according to the
    task's retry_policy. A task_runner that raises, or that exceeds the
    task's timeout_seconds, is treated as a failure.

    Mutates the Task objects inside workflow in place and persists state
    transitions via conn. Raises ValueError if the workflow fails validation
    (e.g. a dependency cycle) before any task runs.

    After this returns, call get_workflow_status(workflow) on the same
    workflow object to check the outcome.
    """
    if not validate_workflow(workflow):
        raise ValueError("workflow is invalid")

    while True:
        current_time = time_source()
        ready = schedule_once(workflow, task_states, current_time, conn)
        if not ready:
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

        for task in ready:
            execute_task(task, conn, current_time)

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(task_runner, task)
                    success = future.result(timeout=task.timeout_seconds)
            except FutureTimeoutError:
                fail_task(task, current_time, conn, task_states)
                continue
            except Exception:
                transition_task(task, TaskState.FAILED, conn, current_time)
                continue

            if success:
                complete_task(task, conn, current_time, task_states)
            else:
                fail_task(task, current_time, conn, task_states)
