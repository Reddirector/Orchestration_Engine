import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from orchestration_engine.executor import execute_task, complete_task, fail_task
from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.scheduler import schedule_once
from orchestration_engine.transitions import transition_task
from orchestration_engine.validation import validate_workflow


def run_workflow(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: Callable[[Task], bool],
    conn: sqlite3.Connection
) -> None:
    if not validate_workflow(workflow):
        raise ValueError("workflow is invalid")

    while True:
        current_time = time_source()
        ready = schedule_once(workflow, task_states, current_time, conn)
        if not ready:
            break

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
