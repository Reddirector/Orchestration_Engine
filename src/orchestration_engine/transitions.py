import sqlite3
from dataclasses import dataclass

from orchestration_engine.errors import PersistenceError
from orchestration_engine.models import Task, TaskState
from orchestration_engine.persistence import log_task_event


@dataclass
class RunContext:
    run_id: str
    next_retry_at: float | None = None
    error: str | None = None


ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.READY, TaskState.CANCELLED},
    TaskState.READY: {TaskState.RUNNING},
    TaskState.RUNNING: {
        TaskState.SUCCEEDED,
        TaskState.RETRY_WAIT,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.RETRY_WAIT: {TaskState.READY},
}


def can_transition(current: TaskState, new: TaskState) -> bool:
    return new in ALLOWED_TRANSITIONS.get(current, set())


def transition_task(
    task: Task,
    new_state: TaskState,
    conn: sqlite3.Connection,
    timestamp: float,
    context: RunContext | None = None,
) -> bool:
    if not can_transition(task.state, new_state):
        return False

    run_id = context.run_id if context is not None else getattr(task, "_run_id", None)
    next_retry_at = context.next_retry_at if context is not None else task.next_retry_at
    error = context.error if context is not None else task.last_error

    try:
        log_task_event(
            conn,
            task_id=task.task_id,
            old_state=task.state.value,
            new_state=new_state.value,
            timestamp=timestamp,
            attempt_count=task.attempt_count,
            workflow_id=task.workflow_id,
            run_id=run_id,
            next_retry_at=next_retry_at,
            error=error,
        )
    except sqlite3.Error as e:
        raise PersistenceError(f"Database error during transition: {e}") from e

    task.state = new_state
    return True
