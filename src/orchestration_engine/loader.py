import json
import sqlite3
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_workflow_status


def load_workflow_from_json(json_data: dict[str, Any]) -> Workflow:
    """
    Parse a workflow definition dict (e.g. loaded from JSON) into a Workflow.

    Does not run the workflow or touch the database. Raises ValueError if
    the workflow or any task is missing a required field.
    """
    try:
        workflow_id = json_data["workflow_id"]
        name = json_data["name"]
        description = json_data["description"]
    except KeyError as e:
        raise ValueError(f"workflow missing required field: {e}") from e

    default_timeout = json_data.get("default_timeout_seconds")

    tasks: list[Task] = []
    for index, task_data in enumerate(json_data["tasks"]):
        try:
            retry_policy = RetryPolicy(
                max_attempts=task_data["retry_policy"]["max_attempts"],
                delay_seconds=task_data["retry_policy"]["delay_seconds"],
            )
            if "timeout_seconds" in task_data:
                timeout_seconds = task_data["timeout_seconds"]
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
            raise ValueError(
                f"task {index} missing required field: {e}") from e
        tasks.append(task)

    return Workflow(
        workflow_id=workflow_id,
        name=name,
        description=description,
        tasks=tasks,
        default_timeout_seconds=default_timeout,
    )


def run_workflow_from_file(
    path: str,
    task_runner: Callable[[Task], bool],
    time_source: Callable[[], float],
    conn: sqlite3.Connection,
) -> WorkflowStatus:
    """
    Load a workflow definition from a JSON file and run it to completion.

    Equivalent to load_workflow_from_json(...) followed by run_workflow(...),
    then returning get_workflow_status(...) on the resulting Workflow. See
    run_workflow for task_runner's contract and retry/timeout behavior.
    """
    with open(path) as f:
        json_data = json.load(f)

    workflow = load_workflow_from_json(json_data)
    task_states: dict[str, TaskState] = {}
    run_workflow(workflow, task_states, time_source, task_runner, conn)

    return get_workflow_status(workflow)
