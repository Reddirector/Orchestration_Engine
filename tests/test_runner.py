import pytest

from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.runner import run_workflow


def test_run_workflow_raises_on_invalid_workflow() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Self-dependent Task",
        description="Task depends on itself",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=["task-1"],
    )

    workflow = Workflow(
        workflow_id="workflow-invalid",
        name="Invalid Workflow",
        description="Should be rejected before scheduling starts",
        tasks=[task],
    )

    task_states: dict[str, TaskState] = {"task-1": TaskState.PENDING}

    with pytest.raises(ValueError):
        run_workflow(
            workflow,
            task_states,
            time_source=lambda: 0.0,
            task_runner=lambda task: True,
        )


def test_run_workflow_executes_task_via_callback() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Simple Task",
        description="Should be executed via the callback",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-callback",
        name="Callback Workflow",
        description="Checks run_workflow drives execution via callback",
        tasks=[task],
    )

    task_states: dict[str, TaskState] = {"task-1": TaskState.PENDING}

    def task_runner(task: Task) -> bool:
        return True

    run_workflow(
        workflow,
        task_states,
        time_source=lambda: 0.0,
        task_runner=task_runner,
    )

    assert task.state == TaskState.SUCCEEDED


def test_run_workflow_retries_using_time_source() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Flaky Task",
        description="Fails once, then succeeds on retry",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-retry-clock",
        name="Retry Clock Workflow",
        description="Checks run_workflow advances time to pick up retries",
        tasks=[task],
    )

    task_states: dict[str, TaskState] = {"task-1": TaskState.PENDING}

    attempts = {"count": 0}

    def task_runner(task: Task) -> bool:
        attempts["count"] += 1
        return attempts["count"] > 1

    clock = {"now": 0.0}

    def time_source() -> float:
        clock["now"] += 10
        return clock["now"]

    run_workflow(
        workflow,
        task_states,
        time_source=time_source,
        task_runner=task_runner,
    )

    assert task.state == TaskState.SUCCEEDED


def test_run_workflow_marks_task_failed_on_runner_exception() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Crashing Task",
        description="task_runner raises instead of returning",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-crash",
        name="Crash Workflow",
        description="Checks run_workflow handles task_runner exceptions",
        tasks=[task],
    )

    task_states: dict[str, TaskState] = {"task-1": TaskState.PENDING}

    def task_runner(task: Task) -> bool:
        raise RuntimeError

    run_workflow(
        workflow,
        task_states,
        time_source=lambda: 0.0,
        task_runner=task_runner,
    )

    assert task.state == TaskState.FAILED


def test_run_workflow_retries_on_timeout() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Slow Task",
        description="Times out on first call, then a retry succeeds",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
        timeout_seconds=1,
    )

    workflow = Workflow(
        workflow_id="workflow-timeout",
        name="Timeout Workflow",
        description="Checks run_workflow retries a task that times out",
        tasks=[task],
    )

    task_states: dict[str, TaskState] = {"task-1": TaskState.PENDING}

    attempts = {"count": 0}

    def task_runner(task: Task) -> bool:
        attempts["count"] += 1
        if attempts["count"] == 1:
            import time
            time.sleep(3)
        return True

    clock = {"now": 0.0}

    def time_source() -> float:
        clock["now"] += 10
        return clock["now"]

    run_workflow(
        workflow,
        task_states,
        time_source=time_source,
        task_runner=task_runner,
    )

    assert task.state == TaskState.SUCCEEDED
