import sqlite3
from orchestration_engine.models import RetryPolicy, Task, TaskState
from orchestration_engine.transitions import can_transition, transition_task


def test_pending_to_ready_is_allowed() -> None:
    assert can_transition(TaskState.PENDING, TaskState.READY) is True


def test_pending_to_succeeded_is_not_allowed() -> None:
    assert can_transition(TaskState.PENDING, TaskState.SUCCEEDED) is False


def test_ready_to_running_is_allowed() -> None:
    assert can_transition(TaskState.READY, TaskState.RUNNING) is True


def test_running_to_succeeded_is_allowed() -> None:
    assert can_transition(TaskState.RUNNING, TaskState.SUCCEEDED) is True


def test_succeeded_to_running_is_not_allowed() -> None:
    assert can_transition(TaskState.SUCCEEDED, TaskState.RUNNING) is False


def test_pending_to_ready_transition(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Test",
        description="Transition test",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )

    assert transition_task(task, TaskState.READY, conn, 0.0) is True
    assert task.state == TaskState.READY


def test_pending_to_succeeded_transition_is_rejected(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Test",
        description="Transition test",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )

    assert transition_task(task, TaskState.SUCCEEDED, conn, 0.0) is False
    assert task.state == TaskState.PENDING


def test_retry_wait_to_ready_is_allowed() -> None:
    assert can_transition(TaskState.RETRY_WAIT, TaskState.READY) is True
