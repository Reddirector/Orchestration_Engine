from orchestration_engine.models import Task, TaskState
from orchestration_engine.transitions import transition_task


def execute_task(task: Task) -> bool:
    if task.state != TaskState.READY:
        return False

    if not transition_task(task, TaskState.RUNNING):
        return False
    task.attempt_count += 1
    return True


def complete_task(task: Task) -> bool:
    if task.state != TaskState.RUNNING:
        return False

    return transition_task(task, TaskState.SUCCEEDED)


def fail_task(task: Task, current_time: float) -> bool:

    if task.state != TaskState.RUNNING:
        return False

    if task.attempt_count < task.retry_policy.max_attempts:
        task.next_retry_at = current_time + task.retry_policy.delay_seconds
        return transition_task(task, TaskState.RETRY_WAIT)

    return transition_task(task, TaskState.FAILED)


def retry_task(task: Task, current_time: float) -> bool:
    if task.state != TaskState.RETRY_WAIT:
        return False

    if task.next_retry_at is None:
        return False

    if current_time < task.next_retry_at:
        return False

    return transition_task(task, TaskState.READY)
