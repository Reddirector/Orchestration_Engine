from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.scheduler import schedule_once


def test_scheduler() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)
    task_a = Task(
        name="Dependies check",
        task_id="task_a",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_b = Task(
        name="Dependies check",
        task_id="task_b",
        dependencies=["task_a"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    workflow = Workflow(
        workflow_id="workflow-ready-check",
        name="Ready Task Check",
        description="Checks which tasks are ready",
        tasks=[task_a, task_b],
    )

    task_states: dict[str, TaskState] = {
        "task_a": TaskState.PENDING,
        "task_b": TaskState.PENDING,

    }

    scheduled = schedule_once(workflow, task_states)

    assert task_a in scheduled
    assert task_b not in scheduled
    assert task_a.state == TaskState.READY
    assert task_b.state == TaskState.PENDING


def test_scheduler_succeeded_and_pending() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)
    task_a = Task(
        name="Dependies check",
        task_id="task_a",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.SUCCEEDED,

    )
    task_b = Task(
        name="Dependies check",
        task_id="task_b",
        dependencies=["task_a"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    workflow = Workflow(
        workflow_id="workflow-ready-check",
        name="Ready Task Check",
        description="Checks which tasks are ready",
        tasks=[task_a, task_b],
    )

    task_states: dict[str, TaskState] = {
        "task_a": TaskState.SUCCEEDED,
        "task_b": TaskState.PENDING,

    }

    scheduled = schedule_once(workflow, task_states)

    assert task_a not in scheduled
    assert task_b in scheduled
    assert task_b.state == TaskState.READY
