import json
from collections.abc import Callable

from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_workflow_status


def load_workflow_from_json(json_data: dict) -> Workflow:
    workflow_id = json_data["workflow_id"]
    name = json_data["name"]
    description = json_data["description"]

    tasks: list[Task] = []
    for task_data in json_data["tasks"]:
        retry_policy = RetryPolicy(
            max_attempts=task_data["retry_policy"]["max_attempts"],
            delay_seconds=task_data["retry_policy"]["delay_seconds"],
        )
        task = Task(
            task_id=task_data["task_id"],
            workflow_id=workflow_id,
            name=task_data["name"],
            description=task_data["description"],
            dependencies=task_data["dependencies"],
            state=TaskState.PENDING,
            retry_policy=retry_policy,
            timeout_seconds=task_data.get("timeout_seconds", 1),
        )
        tasks.append(task)

    return Workflow(
        workflow_id=workflow_id,
        name=name,
        description=description,
        tasks=tasks,
    )


def run_workflow_from_file(
    path: str,
    task_runner: Callable[[Task], bool],
    time_source: Callable[[], float],
    conn,
    task_states: dict,
) -> WorkflowStatus:
    with open(path) as f:
        json_data = json.load(f)

    workflow = load_workflow_from_json(json_data)
    run_workflow(workflow, task_states, time_source, task_runner, conn)

    return get_workflow_status(workflow)
