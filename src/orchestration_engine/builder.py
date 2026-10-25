from __future__ import annotations

from typing import Any, Self

from orchestration_engine.errors import WorkflowValidationError
from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.validation import get_workflow_validation_error


class WorkflowBuilder:
    """
    Fluent builder for constructing and validating Workflow instances.
    """

    def __init__(
        self,
        workflow_id: str,
        name: str = "",
        description: str = "",
        default_timeout_seconds: float | None = None,
    ) -> None:
        self._workflow_id = workflow_id
        self._name = name or workflow_id
        self._description = description
        self._default_timeout_seconds = default_timeout_seconds
        self._tasks: list[Task] = []

    def name(self, name: str) -> Self:
        self._name = name
        return self

    def description(self, description: str) -> Self:
        self._description = description
        return self

    def default_timeout(self, seconds: float | None) -> Self:
        self._default_timeout_seconds = seconds
        return self

    def task(
        self,
        task_id: str,
        name: str = "",
        description: str = "",
        dependencies: list[str] | None = None,
        max_attempts: int = 1,
        delay_seconds: float = 1.0,
        timeout_seconds: float | None = 30.0,
        retry_policy: RetryPolicy | None = None,
    ) -> Self:
        if retry_policy is None:
            policy = RetryPolicy(
                max_attempts=max_attempts, delay_seconds=delay_seconds
            )
        else:
            policy = retry_policy

        effective_timeout = timeout_seconds
        if (
            timeout_seconds == 30.0
            and self._default_timeout_seconds is not None
        ):
            effective_timeout = self._default_timeout_seconds

        task = Task(
            task_id=task_id,
            workflow_id=self._workflow_id,
            name=name or task_id,
            description=description,
            dependencies=list(dependencies or []),
            state=TaskState.PENDING,
            retry_policy=policy,
            timeout_seconds=effective_timeout,
        )
        self._tasks.append(task)
        return self

    def build(self) -> Workflow:
        workflow = Workflow(
            workflow_id=self._workflow_id,
            name=self._name,
            description=self._description,
            tasks=list(self._tasks),
            default_timeout_seconds=self._default_timeout_seconds,
        )
        error = get_workflow_validation_error(workflow)
        if error:
            raise WorkflowValidationError(f"Invalid workflow: {error}")
        return workflow


def workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
    """
    Serialize a Workflow instance to a JSON-compatible dictionary.

    Round-trips losslessly with load_workflow_from_json.
    """
    return {
        "workflow_id": workflow.workflow_id,
        "name": workflow.name,
        "description": workflow.description,
        "default_timeout_seconds": workflow.default_timeout_seconds,
        "tasks": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "description": t.description,
                "dependencies": list(t.dependencies),
                "retry_policy": {
                    "max_attempts": t.retry_policy.max_attempts,
                    "delay_seconds": t.retry_policy.delay_seconds,
                },
                "timeout_seconds": t.timeout_seconds,
            }
            for t in workflow.tasks
        ],
    }
