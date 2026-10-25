import pytest

from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_workflow_status


def test_run_workflow_raises_on_invalid_workflow(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
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
            conn=conn,
        )


def test_run_workflow_executes_task_via_callback(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
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
        conn=conn,
    )

    assert task.state == TaskState.SUCCEEDED


def test_run_workflow_retries_using_time_source(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
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
        conn=conn,
    )

    assert task.state == TaskState.SUCCEEDED


def test_run_workflow_marks_task_failed_on_runner_exception(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
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
        conn=conn,
    )

    assert task.state == TaskState.FAILED


def test_run_workflow_retries_on_timeout(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
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
        conn=conn,
    )

    assert task.state == TaskState.SUCCEEDED


def test_transitive_cancellation_end_to_end(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=1, delay_seconds=1)
    task_a = Task(
        task_id="A",
        workflow_id="wf-e2e-cancel",
        name="Task A",
        description="Always fails",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_b = Task(
        task_id="B",
        workflow_id="wf-e2e-cancel",
        name="Task B",
        description="Depends on A",
        dependencies=["A"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_c = Task(
        task_id="C",
        workflow_id="wf-e2e-cancel",
        name="Task C",
        description="Depends on B",
        dependencies=["B"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_d = Task(
        task_id="D",
        workflow_id="wf-e2e-cancel",
        name="Task D",
        description="Independent",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    workflow = Workflow(
        workflow_id="wf-e2e-cancel",
        name="End-to-End Transitive Cancellation",
        description="Tests transitive cancellation end-to-end",
        tasks=[task_a, task_b, task_c, task_d],
    )
    task_states: dict[str, TaskState] = {}

    def runner(task: Task) -> bool:
        if task.task_id == "A":
            return False
        return True

    run_workflow(
        workflow,
        task_states,
        time_source=lambda: 0.0,
        task_runner=runner,
        conn=conn,
    )

    assert task_a.state == TaskState.FAILED
    assert task_b.state == TaskState.CANCELLED
    assert task_c.state == TaskState.CANCELLED
    assert task_d.state == TaskState.SUCCEEDED
    assert get_workflow_status(workflow) == WorkflowStatus.FAILED


def test_transitive_cancellation_diamond_case(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=1, delay_seconds=1)
    task_a = Task(
        task_id="A",
        workflow_id="wf-diamond-cancel",
        name="Task A",
        description="Always fails",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_b = Task(
        task_id="B",
        workflow_id="wf-diamond-cancel",
        name="Task B",
        description="Depends on A",
        dependencies=["A"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_d = Task(
        task_id="D",
        workflow_id="wf-diamond-cancel",
        name="Task D",
        description="Independent",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_e = Task(
        task_id="E",
        workflow_id="wf-diamond-cancel",
        name="Task E",
        description="Depends on B (cancelled) and D (succeeded)",
        dependencies=["B", "D"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    workflow = Workflow(
        workflow_id="wf-diamond-cancel",
        name="Diamond Cancellation",
        description="Tests diamond dependency cancellation",
        tasks=[task_a, task_b, task_d, task_e],
    )
    task_states: dict[str, TaskState] = {}

    def runner(task: Task) -> bool:
        if task.task_id == "A":
            return False
        return True

    run_workflow(
        workflow,
        task_states,
        time_source=lambda: 0.0,
        task_runner=runner,
        conn=conn,
    )

    assert task_a.state == TaskState.FAILED
    assert task_b.state == TaskState.CANCELLED
    assert task_d.state == TaskState.SUCCEEDED
    assert task_e.state == TaskState.CANCELLED
    assert get_workflow_status(workflow) == WorkflowStatus.FAILED
