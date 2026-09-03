from orchestration_engine.models import Task, TaskState

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


def transition_task(task: Task, new_state: TaskState) -> bool:
    if not can_transition(task.state, new_state):
        return False

    task.state = new_state
    return True
