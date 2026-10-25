import sqlite3

from orchestration_engine.models import Task, TaskState
from orchestration_engine.transitions import transition_task


def execute_task(task: Task, conn: sqlite3.Connection, timestamp: float) -> bool:
    if task.state != TaskState.READY:
        return False

    if not transition_task(task, TaskState.RUNNING, conn, timestamp):
        return False
    task.attempt_count += 1
    return True


def complete_task(
    task: Task,
    conn: sqlite3.Connection,
    timestamp: float,
    task_states: dict[str, TaskState],
) -> bool:
    if task.state != TaskState.RUNNING:
        return False

    success = transition_task(task, TaskState.SUCCEEDED, conn, timestamp)
    if success:
        task_states[task.task_id] = TaskState.SUCCEEDED
    return success


def fail_task(
    task: Task,
    current_time: float,
    conn: sqlite3.Connection,
    task_states: dict[str, TaskState],
) -> bool:
    if task.state != TaskState.RUNNING:
        return False

    if task.attempt_count < task.retry_policy.max_attempts:
        task.next_retry_at = current_time + calculate_retry_delay(task)
        retried = transition_task(
            task, TaskState.RETRY_WAIT, conn, current_time)
        if retried:
            task_states[task.task_id] = TaskState.RETRY_WAIT
        return retried

    failed = transition_task(task, TaskState.FAILED, conn, current_time)
    if failed:
        task_states[task.task_id] = TaskState.FAILED
    return failed


def retry_task(
    task: Task,
    current_time: float,
    conn: sqlite3.Connection,
    task_states: dict[str, TaskState],
) -> bool:
    if task.state != TaskState.RETRY_WAIT:
        return False

    if task.next_retry_at is None:
        return False

    if current_time < task.next_retry_at:
        return False

    ready = transition_task(task, TaskState.READY, conn, current_time)
    if ready:
        task_states[task.task_id] = TaskState.READY
    return ready


def calculate_retry_delay(task: Task) -> float:
    base_delay = task.retry_policy.delay_seconds
    attempt_count = task.attempt_count

    return float(base_delay * (2 ** (attempt_count - 1)))
