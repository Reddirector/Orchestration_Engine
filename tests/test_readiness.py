import sqlite3

from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.readiness import (
    cancel_blocked_tasks,
    get_ready_tasks,
    is_task_ready,
    mark_ready_tasks,
)


def test_task_with_no_dependencies_is_ready() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        name="Dependies check",
        task_id="check-1",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_states: dict[str, TaskState] = {}

    assert is_task_ready(task, task_states) is True


def test_task_with_dependencies_is_ready() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        name="Dependies check",
        task_id="check-1",
        workflow_id="test-workflow",
        dependencies=["task-A"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_states: dict[str, TaskState] = {
        "task-A": TaskState.PENDING
    }

    assert is_task_ready(task, task_states) is False


def test_task_with_and_succeeded_dependencies_is_ready() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_b = Task(
        name="Dependies check",
        task_id="check-3",
        workflow_id="test-workflow",
        dependencies=["task-A"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_states: dict[str, TaskState] = {
        "task-A": TaskState.SUCCEEDED
    }

    assert is_task_ready(task_b, task_states) is True


def test_task_ready_or_not() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_h = Task(
        name="Dependies check",
        task_id="check-4",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_j = Task(
        name="Dependies check",
        task_id="check-5",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_l = Task(
        name="Dependies check",
        task_id="check-6",
        workflow_id="test-workflow",
        dependencies=["check-4"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    workflow = Workflow(
        workflow_id="workflow-ready-check",
        name="Ready Task Check",
        description="Checks which tasks are ready",
        tasks=[task_h, task_j, task_l],
    )

    task_states: dict[str, TaskState] = {
        "check-4": TaskState.PENDING,
        "check-5": TaskState.PENDING,
        "check-6": TaskState.PENDING,
    }

    ready_tasks = get_ready_tasks(workflow, task_states)

    assert task_h in ready_tasks
    assert task_j in ready_tasks
    assert task_l not in ready_tasks


def test_task_ready() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_h = Task(
        name="Dependies check",
        task_id="check-4",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_j = Task(
        name="Dependies check",
        task_id="check-5",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_l = Task(
        name="Dependies check",
        task_id="check-6",
        workflow_id="test-workflow",
        dependencies=["check-4"],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    workflow = Workflow(
        workflow_id="workflow-ready-check",
        name="Ready Task Check",
        description="Checks which tasks are ready",
        tasks=[task_h, task_j, task_l],
    )

    task_states: dict[str, TaskState] = {
        "check-4": TaskState.SUCCEEDED,
        "check-5": TaskState.PENDING,
        "check-6": TaskState.PENDING,
    }

    ready_tasks = get_ready_tasks(workflow, task_states)

    assert task_h in ready_tasks
    assert task_j in ready_tasks
    assert task_l in ready_tasks


def test_mark_ready_task(conn: sqlite3.Connection) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)
    task_a = Task(
        name="Dependies check",
        task_id="task_a",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_b = Task(
        name="Dependies check",
        task_id="task_b",
        workflow_id="test-workflow",
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
    marked = mark_ready_tasks(workflow, task_states, conn, 0.0)
    assert task_a.state == TaskState.READY
    assert task_states["task_a"] == TaskState.READY
    assert task_b.state == TaskState.PENDING
    assert task_a in marked
    assert task_b not in marked


def test_task_becomes_ready_after_dependency_succeeds(conn: sqlite3.Connection) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)
    task_a = Task(
        name="Dependies check",
        task_id="task_a",
        workflow_id="test-workflow",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_b = Task(
        name="Dependies check",
        task_id="task_b",
        workflow_id="test-workflow",
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
    task_a.state = TaskState.SUCCEEDED
    task_states["task_a"] = TaskState.SUCCEEDED
    marked = mark_ready_tasks(workflow, task_states, conn, 0.0)

    assert task_b.state == TaskState.READY
    assert task_states["task_b"] == TaskState.READY
    assert task_b in marked


def test_dependent_task_cancelled_when_dependency_failed(conn: sqlite3.Connection) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task_a",
        workflow_id="test-workflow",
        name="Upstream task",
        description="Fails to trigger cancellation of dependent",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.FAILED,
    )
    task_b = Task(
        task_id="task_b",
        workflow_id="test-workflow",
        name="Downstream task",
        description="Should be cancelled since its dependency failed",
        dependencies=["task_a"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    workflow = Workflow(
        workflow_id="wf-fail-propagation",
        name="Failure Propagation Test",
        description="Checks that dependents get cancelled on upstream failure",
        tasks=[task_a, task_b],
    )

    task_states: dict[str, TaskState] = {
        "task_a": TaskState.FAILED,
        "task_b": TaskState.PENDING,
    }

    cancel_blocked_tasks(workflow, task_states, conn, 0.0)

    assert task_b.state == TaskState.CANCELLED


def test_transitive_cancellation_unit(conn: sqlite3.Connection) -> None:
    from orchestration_engine.scheduler import schedule_once

    retry_policy = RetryPolicy(max_attempts=1, delay_seconds=1)
    task_a = Task(
        task_id="A",
        workflow_id="wf-transitive",
        name="Task A",
        description="Fails",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.FAILED,
    )
    task_b = Task(
        task_id="B",
        workflow_id="wf-transitive",
        name="Task B",
        description="Depends on A",
        dependencies=["A"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    task_c = Task(
        task_id="C",
        workflow_id="wf-transitive",
        name="Task C",
        description="Depends on B",
        dependencies=["B"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    workflow = Workflow(
        workflow_id="wf-transitive",
        name="Transitive Cancellation Workflow",
        description="Tests transitive cancellation",
        tasks=[task_a, task_b, task_c],
    )
    task_states: dict[str, TaskState] = {
        "A": TaskState.FAILED,
        "B": TaskState.PENDING,
        "C": TaskState.PENDING,
    }

    cancel_blocked_tasks(workflow, task_states, conn, 0.0)

    assert task_b.state == TaskState.CANCELLED
    assert task_states["B"] == TaskState.CANCELLED
    assert task_c.state == TaskState.CANCELLED
    assert task_states["C"] == TaskState.CANCELLED

    # Also test via schedule_once
    task_b.state = TaskState.PENDING
    task_c.state = TaskState.PENDING
    task_states["B"] = TaskState.PENDING
    task_states["C"] = TaskState.PENDING

    schedule_once(workflow, task_states, 0.0, conn)

    assert task_b.state == TaskState.CANCELLED
    assert task_states["B"] == TaskState.CANCELLED
    assert task_c.state == TaskState.CANCELLED
    assert task_states["C"] == TaskState.CANCELLED
