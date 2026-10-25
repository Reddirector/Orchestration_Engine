import logging
import sqlite3

from orchestration_engine.models import Task, TaskState
from orchestration_engine.transitions import transition_task

logger = logging.getLogger("orchestration_engine")


def execute_task(task: Task, conn: sqlite3.Connection, timestamp: float) -> bool:
    if task.state != TaskState.READY:
        return False

    task.attempt_count += 1
    if not transition_task(task, TaskState.RUNNING, conn, timestamp):
        task.attempt_count -= 1
        return False
    return True


def complete_task(
    task: Task,
    conn: sqlite3.Connection,
    timestamp: float,
    task_states: dict[str, TaskState] | None = None,
) -> bool:
    if task.state != TaskState.RUNNING:
        return False

    return transition_task(task, TaskState.SUCCEEDED, conn, timestamp, task_states=task_states)


def fail_task(
    task: Task,
    current_time: float,
    conn: sqlite3.Connection,
    task_states: dict[str, TaskState] | None = None,
) -> bool:
    if task.state != TaskState.RUNNING:
        return False

    if task.attempt_count < task.retry_policy.max_attempts:
        task.next_retry_at = current_time + calculate_retry_delay(task)
        logger.warning(
            "Task '%s' failed attempt %s/%s; retrying at %s",
            task.task_id,
            task.attempt_count,
            task.retry_policy.max_attempts,
            task.next_retry_at,
            extra={
                "workflow_id": task.workflow_id,
                "run_id": getattr(task, "_run_id", None),
                "task_id": task.task_id,
                "old_state": task.state.value,
                "new_state": TaskState.RETRY_WAIT.value,
                "attempt": task.attempt_count,
            },
        )
        return transition_task(
            task, TaskState.RETRY_WAIT, conn, current_time, task_states=task_states
        )

    return transition_task(
        task, TaskState.FAILED, conn, current_time, task_states=task_states
    )


def retry_task(
    task: Task,
    current_time: float,
    conn: sqlite3.Connection,
    task_states: dict[str, TaskState] | None = None,
) -> bool:
    if task.state != TaskState.RETRY_WAIT:
        return False

    if task.next_retry_at is None:
        return False

    if current_time < task.next_retry_at:
        return False

    return transition_task(task, TaskState.READY, conn, current_time, task_states=task_states)


def calculate_retry_delay(task: Task) -> float:
    """
    Calculate retry delay using exponential backoff:
    delay = delay_seconds * (2 ** (attempt_count - 1))
    """
    base_delay = task.retry_policy.delay_seconds
    attempt_count = task.attempt_count

    return float(base_delay * (2 ** (attempt_count - 1)))
