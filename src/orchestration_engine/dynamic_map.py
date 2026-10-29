"""
Dynamic Task Mapping and Fan-Out / Fan-In for Orchestration Engine.

Enables dynamically generating parallel child tasks from an input collection
and gathering their results in a downstream reducer (fan-in) task.
Zero external runtime dependencies.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from orchestration_engine.models import RetryPolicy, Task, TaskState


def map_tasks(
    base_task_id: str,
    items: Sequence[Any],
    name_prefix: str = "",
    dependencies: list[str] | None = None,
    retry_policy: RetryPolicy | None = None,
    timeout_seconds: float | None = 30.0,
    workflow_id: str = "",
) -> list[Task]:
    """
    Generate a collection of parallel tasks mapped over input items (fan-out).

    Each generated task receives its item and index in `task.inputs`:
    `{"item": items[i], "index": i, "total": len(items)}`.

    Args:
        base_task_id: Prefix identifier for the mapped child tasks.
        items: Sequence of items to map over.
        name_prefix: Optional prefix for human-readable task names.
        dependencies: Task IDs that all mapped child tasks must wait for.
        retry_policy: Optional retry policy applied to all mapped tasks.
        timeout_seconds: Timeout in seconds for each mapped task.
        workflow_id: ID of the parent workflow.

    Returns:
        List of initialized Task instances ready to add to a Workflow.
    """
    policy = retry_policy or RetryPolicy(max_attempts=1, delay_seconds=1.0)
    deps = list(dependencies or [])
    tasks: list[Task] = []

    for idx, item in enumerate(items):
        t_id = f"{base_task_id}_{idx}"
        t_name = f"{name_prefix or base_task_id} [{idx + 1}/{len(items)}]"
        t = Task(
            task_id=t_id,
            workflow_id=workflow_id,
            name=t_name,
            description=f"Mapped task {idx + 1} of {len(items)} for {base_task_id}",
            dependencies=list(deps),
            state=TaskState.PENDING,
            retry_policy=policy,
            timeout_seconds=timeout_seconds,
            inputs={"item": item, "index": idx, "total": len(items)},
        )
        tasks.append(t)

    return tasks


def fan_in_task(
    task_id: str,
    mapped_tasks: Sequence[Task | str],
    name: str = "",
    description: str = "",
    retry_policy: RetryPolicy | None = None,
    timeout_seconds: float | None = 30.0,
    workflow_id: str = "",
) -> Task:
    """
    Generate an aggregation task that waits on all mapped child tasks (fan-in).

    Args:
        task_id: Unique task ID for the reducer.
        mapped_tasks: List of Task instances or string task IDs to wait for.
        name: Human-readable name.
        description: Human-readable description.
        retry_policy: Optional retry policy.
        timeout_seconds: Timeout in seconds.
        workflow_id: ID of the parent workflow.

    Returns:
        A Task instance configured with dependencies on all mapped tasks.
    """
    deps = [t.task_id if isinstance(t, Task) else str(t) for t in mapped_tasks]
    policy = retry_policy or RetryPolicy(max_attempts=1, delay_seconds=1.0)

    return Task(
        task_id=task_id,
        workflow_id=workflow_id,
        name=name or task_id,
        description=description or f"Aggregator / Fan-in for {len(deps)} mapped tasks",
        dependencies=deps,
        state=TaskState.PENDING,
        retry_policy=policy,
        timeout_seconds=timeout_seconds,
    )
