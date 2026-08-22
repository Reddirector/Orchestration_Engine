from orchestration_engine.models import Workflow


def has_cycle(
    task_id: str,
    dependencies: dict[str, list[str]],
    visiting: set[str],
    visited: set[str],
) -> bool:
    if task_id in visiting:
        return True

    if task_id in visited:
        return False

    visiting.add(task_id)

    for dependency in dependencies.get(task_id, []):
        if has_cycle(dependency, dependencies, visiting, visited):
            return True

    visiting.remove(task_id)
    visited.add(task_id)

    return False


def validate_workflow(workflow: Workflow) -> bool:
    valid_ids = {task.task_id for task in workflow.tasks}

    if len(valid_ids) != len(workflow.tasks):
        return False

    dependencies = {
        task.task_id: task.dependencies
        for task in workflow.tasks
    }

    for task in workflow.tasks:
        for dependency in task.dependencies:
            if dependency == task.task_id:
                return False

            if dependency not in valid_ids:
                return False

    visiting: set[str] = set()
    visited: set[str] = set()

    for task in workflow.tasks:
        if has_cycle(task.task_id, dependencies, visiting, visited):
            return False

    return True
