import sqlite3

from orchestration_engine.models import Task, TaskState
from orchestration_engine.persistence import log_task_event

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
) -> bool:
    if not can_transition(task.state, new_state):
        return False

    log_task_event(
        conn,
        task_id=task.task_id,
        old_state=task.state,
        new_state=new_state,
        timestamp=timestamp,
        attempt_count=task.attempt_count,
        workflow_id=task.workflow_id,
    )

    task.state = new_state
    return True
