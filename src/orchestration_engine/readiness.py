import sqlite3

from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.transitions import transition_task


def is_task_ready(
    task: Task,
    task_states: dict[str, TaskState],
) -> bool:
    if not task.dependencies:
        return True

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
    conn: sqlite3.Connection,
    timestamp: float,
) -> list[Task]:
    ready_tasks = get_ready_tasks(workflow, task_states)
    for task in ready_tasks:
        if transition_task(task, TaskState.READY, conn, timestamp):
            task_states[task.task_id] = TaskState.READY

    return ready_tasks


def get_blocked_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState],
) -> list[Task]:
    blocked_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.PENDING:
            for dependency in task.dependencies:
                if task_states.get(dependency) == TaskState.FAILED:
                    blocked_tasks.append(task)
                    break

    return blocked_tasks


def cancel_blocked_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    conn: sqlite3.Connection,
    timestamp: float,
) -> list[Task]:
    blocked_tasks = get_blocked_tasks(workflow, task_states)
    for task in blocked_tasks:
        if transition_task(task, TaskState.CANCELLED, conn, timestamp):
            task_states[task.task_id] = TaskState.CANCELLED

    return blocked_tasks
