import json
import os
import sqlite3
from collections.abc import Callable
from typing import Any, Literal

from orchestration_engine.errors import OrchestrationError, WorkflowDefinitionError
from orchestration_engine.models import (
    Hooks,
    RetryPolicy,
    Task,
    TaskResult,
    TaskState,
    Workflow,
    WorkflowStatus,
)
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_workflow_status

MAX_WORKFLOW_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def load_workflow_from_json(
    json_data: dict[str, Any],
    *,
    collect_errors: bool = False,
) -> Workflow:
    """
    Parse a workflow definition dict (e.g. loaded from JSON) into a Workflow.

    Does not run the workflow or touch the database. Raises WorkflowDefinitionError
    if the workflow or any task is missing a required field or has invalid types.
    When collect_errors=True, all errors are accumulated and raised as a single
    WorkflowDefinitionError with an .errors list containing JSON-pointer paths.
    """
    if collect_errors:
        errors: list[str] = []
        if "workflow_id" not in json_data:
            errors.append("/workflow_id: missing required field")
        elif not isinstance(json_data["workflow_id"], str) or not json_data["workflow_id"]:
            errors.append("/workflow_id: must be a non-empty string")

        if "name" not in json_data:
            errors.append("/name: missing required field")
        elif not isinstance(json_data["name"], str):
            errors.append("/name: must be a string")

        if "description" not in json_data:
            errors.append("/description: missing required field")
        elif not isinstance(json_data["description"], str):
            errors.append("/description: must be a string")

        raw_default_to = json_data.get("default_timeout_seconds")
        if raw_default_to is not None:
            if (
                isinstance(raw_default_to, bool)
                or not isinstance(raw_default_to, (int, float))
                or raw_default_to < 0
            ):
                errors.append(
                    "/default_timeout_seconds: must be a non-negative number or null"
                )

        if "tasks" not in json_data:
            errors.append("/tasks: missing required field")
        elif not isinstance(json_data["tasks"], list):
            errors.append("/tasks: must be a list")
        else:
            for index, task_data in enumerate(json_data["tasks"]):
                ptr = f"/tasks/{index}"
                if not isinstance(task_data, dict):
                    errors.append(f"{ptr}: must be an object")
                    continue

                if "task_id" not in task_data:
                    errors.append(f"{ptr}/task_id: missing required field")
                elif not isinstance(task_data["task_id"], str) or not task_data["task_id"]:
                    errors.append(f"{ptr}/task_id: must be a non-empty string")

                if "name" not in task_data:
                    errors.append(f"{ptr}/name: missing required field")
                elif not isinstance(task_data["name"], str):
                    errors.append(f"{ptr}/name: must be a string")

                if "description" not in task_data:
                    errors.append(f"{ptr}/description: missing required field")
                elif not isinstance(task_data["description"], str):
                    errors.append(f"{ptr}/description: must be a string")

                if "dependencies" not in task_data:
                    errors.append(f"{ptr}/dependencies: missing required field")
                elif not isinstance(task_data["dependencies"], list):
                    errors.append(f"{ptr}/dependencies: must be a list")
                else:
                    for d_i, dep in enumerate(task_data["dependencies"]):
                        if not isinstance(dep, str):
                            errors.append(f"{ptr}/dependencies/{d_i}: must be a string")

                if "retry_policy" not in task_data:
                    errors.append(f"{ptr}/retry_policy: missing required field")
                elif not isinstance(task_data["retry_policy"], dict):
                    errors.append(f"{ptr}/retry_policy: must be an object")
                else:
                    rp = task_data["retry_policy"]
                    if "max_attempts" not in rp:
                        errors.append(f"{ptr}/retry_policy/max_attempts: missing required field")
                    elif (
                        isinstance(rp["max_attempts"], bool)
                        or not isinstance(rp["max_attempts"], int)
                        or rp["max_attempts"] < 1
                    ):
                        errors.append(f"{ptr}/retry_policy/max_attempts: must be an integer >= 1")

                    if "delay_seconds" not in rp:
                        errors.append(f"{ptr}/retry_policy/delay_seconds: missing required field")
                    elif (
                        isinstance(rp["delay_seconds"], bool)
                        or not isinstance(rp["delay_seconds"], (int, float))
                        or rp["delay_seconds"] < 0
                    ):
                        errors.append(
                            f"{ptr}/retry_policy/delay_seconds: must be a non-negative number"
                        )

                if "timeout_seconds" in task_data:
                    raw_to = task_data["timeout_seconds"]
                    if raw_to is not None and (
                        isinstance(raw_to, bool)
                        or not isinstance(raw_to, (int, float))
                        or raw_to < 0
                    ):
                        errors.append(
                            f"{ptr}/timeout_seconds: must be a non-negative number or null"
                        )

        if errors:
            raise WorkflowDefinitionError(
                f"Workflow definition has {len(errors)} error(s): {'; '.join(errors)}",
                errors=errors,
            )

    try:
        workflow_id = json_data["workflow_id"]
        name = json_data["name"]
        description = json_data["description"]
    except KeyError as e:
        raise WorkflowDefinitionError(f"workflow missing required field: {e}") from e

    default_timeout = json_data.get("default_timeout_seconds")
    if default_timeout is not None:
        if (
            isinstance(default_timeout, bool)
            or not isinstance(default_timeout, (int, float))
            or default_timeout < 0
        ):
            raise WorkflowDefinitionError(
                "workflow: default_timeout_seconds must be a non-negative number, "
                f"got {default_timeout!r}"
            )
        default_timeout = float(default_timeout)

    tasks: list[Task] = []
    for index, task_data in enumerate(json_data["tasks"]):
        task_id = task_data.get("task_id", f"index {index}")
        try:
            policy_data = task_data["retry_policy"]
            max_attempts = policy_data["max_attempts"]
            if (
                isinstance(max_attempts, bool)
                or not isinstance(max_attempts, int)
                or max_attempts < 1
            ):
                raise WorkflowDefinitionError(
                    f"task {task_id}: retry_policy.max_attempts must be an integer >= 1, "
                    f"got {max_attempts!r}"
                )

            delay_seconds = policy_data["delay_seconds"]
            if (
                isinstance(delay_seconds, bool)
                or not isinstance(delay_seconds, (int, float))
                or delay_seconds < 0
            ):
                raise WorkflowDefinitionError(
                    f"task {task_id}: retry_policy.delay_seconds must be a non-negative number, "
                    f"got {delay_seconds!r}"
                )

            retry_policy = RetryPolicy(
                max_attempts=max_attempts,
                delay_seconds=float(delay_seconds),
            )

            if "timeout_seconds" in task_data:
                raw_timeout = task_data["timeout_seconds"]
                if raw_timeout is not None:
                    if (
                        isinstance(raw_timeout, bool)
                        or not isinstance(raw_timeout, (int, float))
                        or raw_timeout < 0
                    ):
                        raise WorkflowDefinitionError(
                            f"task {task_id}: timeout_seconds must be a non-negative number "
                            f"or null, got {raw_timeout!r}"
                        )
                    timeout_seconds = float(raw_timeout)
                else:
                    timeout_seconds = None
            elif default_timeout is not None:
                timeout_seconds = default_timeout
            else:
                timeout_seconds = 30.0

            task = Task(
                task_id=task_data["task_id"],
                workflow_id=workflow_id,
                name=task_data["name"],
                description=task_data["description"],
                dependencies=task_data["dependencies"],
                state=TaskState.PENDING,
                retry_policy=retry_policy,
                timeout_seconds=timeout_seconds,
            )
        except KeyError as e:
            raise WorkflowDefinitionError(
                f"task {index} missing required field: {e}") from e
        tasks.append(task)

    return Workflow(
        workflow_id=workflow_id,
        name=name,
        description=description,
        tasks=tasks,
        default_timeout_seconds=default_timeout,
    )


ExecutorType = Literal["thread", "process", "_inline"]


def run_workflow_from_file(
    path: str,
    task_runner: Callable[[Task], bool | TaskResult],
    time_source: Callable[[], float],
    conn: sqlite3.Connection,
    *,
    run_id: str | None = None,
    max_concurrency: int = 1,
    executor: ExecutorType = "thread",
    hooks: Hooks | None = None,
) -> WorkflowStatus:
    """
    Load a workflow definition from a JSON file and run it to completion.

    Equivalent to load_workflow_from_json(...) followed by run_workflow(...),
    then returning get_workflow_status(...) on the resulting Workflow. See
    run_workflow for task_runner's contract and retry/timeout behavior.
    """
    if os.path.exists(path) and os.path.getsize(path) > MAX_WORKFLOW_FILE_SIZE:
        raise WorkflowDefinitionError(
            f"Workflow file '{path}' exceeds maximum allowed size of {MAX_WORKFLOW_FILE_SIZE} bytes"
        )

    with open(path) as f:
        json_data = json.load(f)

    workflow = load_workflow_from_json(json_data)
    task_states: dict[str, TaskState] = {}
    run_workflow(
        workflow,
        task_states,
        time_source,
        task_runner,
        conn,
        run_id=run_id,
        max_concurrency=max_concurrency,
        executor=executor,
        hooks=hooks,
    )

    return get_workflow_status(workflow)


def load_workflow_from_yaml(
    source: str | os.PathLike[str] | Any,
    *,
    collect_errors: bool = False,
) -> Workflow:
    """
    Parse a YAML workflow definition (file path, YAML string, or stream) into a Workflow.

    Requires the optional 'yaml' extra (PyYAML). Raises OrchestrationError if PyYAML
    is not installed.
    """
    try:
        import yaml
    except ImportError as e:
        raise OrchestrationError(
            "PyYAML is required to load workflows from YAML. "
            "Install it with: pip install 'orchestration-engine[yaml]'"
        ) from e

    data: Any
    if isinstance(source, (str, os.PathLike)):
        try:
            if os.path.exists(source) and os.path.getsize(source) > MAX_WORKFLOW_FILE_SIZE:
                raise WorkflowDefinitionError(
                    f"Workflow file '{source}' exceeds maximum allowed size "
                    f"of {MAX_WORKFLOW_FILE_SIZE} bytes"
                )
            with open(source) as f:
                data = yaml.safe_load(f)
        except (OSError, FileNotFoundError):
            if isinstance(source, str) and ("\n" in source or ":" in source):
                data = yaml.safe_load(source)
            else:
                raise
    else:
        data = yaml.safe_load(source)

    if not isinstance(data, dict):
        raise WorkflowDefinitionError("YAML workflow definition must be a mapping/object")

    return load_workflow_from_json(data, collect_errors=collect_errors)

