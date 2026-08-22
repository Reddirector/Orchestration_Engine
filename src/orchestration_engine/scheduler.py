from orchestration_engine.models import Task, TaskState, Workflow
from orchestration_engine.readiness import mark_ready_tasks


def schedule_once(
    workflow: Workflow,
    task_states: dict[str, TaskState],
) -> list[Task]:
    ready_tasks = mark_ready_tasks(workflow, task_states)

    return ready_tasks
