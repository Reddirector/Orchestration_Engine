import sqlite3

from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.transitions import transition_task


def is_task_ready(
    task: Task,
    task_states: dict[str, TaskState] | None = None,
    workflow: Workflow | None = None,
) -> bool:
    if not task.dependencies:
        return True

    task_map: dict[str, TaskState] = {}
    if workflow is not None:
        task_map = {t.task_id: t.state for t in workflow.tasks}

    for dependency in task.dependencies:
        dep_state = task_map.get(dependency)
        if dep_state is None and task_states is not None:
            dep_state = task_states.get(dependency)
        elif (
            task_states is not None
            and dep_state != TaskState.SUCCEEDED
            and task_states.get(dependency) == TaskState.SUCCEEDED
        ):
            dep_state = TaskState.SUCCEEDED

        if dep_state != TaskState.SUCCEEDED:
            return False

    return True


def get_ready_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState] | None = None,
) -> list[Task]:
    task_map = {t.task_id: t.state for t in workflow.tasks}
    ready_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.PENDING:
            deps_succeeded = all(
                task_map.get(dep) == TaskState.SUCCEEDED
                or (task_states is not None and task_states.get(dep) == TaskState.SUCCEEDED)
                for dep in task.dependencies
            )
            if deps_succeeded:
                ready_tasks.append(task)

    return ready_tasks


def mark_ready_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState] | None,
    conn: sqlite3.Connection,
    timestamp: float,
) -> list[Task]:
    ready_tasks = get_ready_tasks(workflow, task_states)
    for task in ready_tasks:
        transition_task(task, TaskState.READY, conn, timestamp, task_states=task_states)

    return ready_tasks


def get_blocked_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState] | None = None,
) -> list[Task]:
    task_map = {t.task_id: t.state for t in workflow.tasks}
    blocked_tasks: list[Task] = []

    for task in workflow.tasks:
        if task.state == TaskState.PENDING:
            for dependency in task.dependencies:
                dep_state = task_map.get(dependency)
                if (
                    dep_state in (TaskState.FAILED, TaskState.CANCELLED)
                    or (
                        task_states is not None
                        and task_states.get(dependency) in (TaskState.FAILED, TaskState.CANCELLED)
                    )
                ):
                    blocked_tasks.append(task)
                    break

    return blocked_tasks


def cancel_blocked_tasks(
    workflow: Workflow,
    task_states: dict[str, TaskState] | None,
    conn: sqlite3.Connection,
    timestamp: float,
) -> list[Task]:
    all_cancelled: list[Task] = []
    while True:
        blocked_tasks = get_blocked_tasks(workflow, task_states)
        if not blocked_tasks:
            break
        cancelled_in_pass = 0
        for task in blocked_tasks:
            if transition_task(
                task, TaskState.CANCELLED, conn, timestamp, task_states=task_states
            ):
                all_cancelled.append(task)
                cancelled_in_pass += 1
        if cancelled_in_pass == 0:
            break

    return all_cancelled
