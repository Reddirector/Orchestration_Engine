from orchestration_engine.models import Workflow

MAX_TASKS_PER_WORKFLOW = 5000
MAX_DEPENDENCIES_PER_TASK = 500


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


def get_workflow_validation_error(workflow: Workflow) -> str | None:
    """
    Validate workflow structure and task parameters.
    Returns None if valid, or a human-readable error reason if invalid.
    """
    if workflow.default_timeout_seconds is not None:
        if (
            isinstance(workflow.default_timeout_seconds, bool)
            or not isinstance(workflow.default_timeout_seconds, (int, float))
            or workflow.default_timeout_seconds < 0
        ):
            return (
                "workflow default_timeout_seconds must be a non-negative number, "
                f"got {workflow.default_timeout_seconds!r}"
            )

    if len(workflow.tasks) > MAX_TASKS_PER_WORKFLOW:
        return (
            f"workflow task count ({len(workflow.tasks)}) exceeds limit of {MAX_TASKS_PER_WORKFLOW}"
        )

    seen_ids: set[str] = set()
    for task in workflow.tasks:
        if task.task_id in seen_ids:
            return f"duplicate task id: {task.task_id}"
        seen_ids.add(task.task_id)

    valid_ids = seen_ids
    dependencies = {task.task_id: task.dependencies for task in workflow.tasks}

    for task in workflow.tasks:
        if len(task.dependencies) > MAX_DEPENDENCIES_PER_TASK:
            return (
                f"task {task.task_id}: dependencies count ({len(task.dependencies)}) "
                f"exceeds limit of {MAX_DEPENDENCIES_PER_TASK}"
            )
        policy = task.retry_policy
        if (
            isinstance(policy.max_attempts, bool)
            or not isinstance(policy.max_attempts, int)
            or policy.max_attempts < 1
        ):
            return (
                f"task {task.task_id}: retry_policy.max_attempts must be an integer >= 1, "
                f"got {policy.max_attempts!r}"
            )

        if (
            isinstance(policy.delay_seconds, bool)
            or not isinstance(policy.delay_seconds, (int, float))
            or policy.delay_seconds < 0
        ):
            return (
                f"task {task.task_id}: retry_policy.delay_seconds must be a number >= 0, "
                f"got {policy.delay_seconds!r}"
            )

        if task.timeout_seconds is not None:
            if (
                isinstance(task.timeout_seconds, bool)
                or not isinstance(task.timeout_seconds, (int, float))
                or task.timeout_seconds < 0
            ):
                return (
                    f"task {task.task_id}: timeout_seconds must be a number >= 0 or None, "
                    f"got {task.timeout_seconds!r}"
                )

        for dependency in task.dependencies:
            if dependency == task.task_id:
                return f"task {task.task_id} has a self-dependency"

            if dependency not in valid_ids:
                return f"task {task.task_id} depends on unknown task {dependency}"

    visiting: set[str] = set()
    visited: set[str] = set()

    for task in workflow.tasks:
        if has_cycle(task.task_id, dependencies, visiting, visited):
            return "cycle detected in workflow dependencies"

    return None


def validate_workflow(workflow: Workflow) -> bool:
    return get_workflow_validation_error(workflow) is None
