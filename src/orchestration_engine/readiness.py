from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.transitions import transition_task


def is_task_ready(
    task: Task,
    task_states: dict[str, TaskState],
) -> bool:
    # if the dependencies is empty
    if not task.dependencies:
        return True

    # if the are not empty dependencies is empty
    for dependency in task.dependencies:
        if task_states.get(dependency) != TaskState.SUCCEEDED:
            return False

    return True


def get_ready_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState],
) -> list[Task]:
    ready_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.PENDING and is_task_ready(task, task_states):
            ready_tasks.append(task)

    return ready_tasks


def mark_ready_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState],
) -> list[Task]:
    ready_tasks = get_ready_tasks(workflow, task_states)
    for task in ready_tasks:
        if transition_task(task, TaskState.READY):
            task_states[task.task_id] = TaskState.READY

    return ready_tasks
