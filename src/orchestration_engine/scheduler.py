from orchestration_engine.executor import retry_task
from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.readiness import mark_ready_tasks, cancel_blocked_tasks


def schedule_once(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    current_time: float,
) -> list[Task]:
    retried_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.RETRY_WAIT:
            if retry_task(task, current_time):
                retried_tasks.append(task)

    cancel_blocked_tasks(workflow, task_states)
    ready_tasks = mark_ready_tasks(workflow, task_states)

    return ready_tasks + retried_tasks
