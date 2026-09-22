from orchestration_engine.executor import complete_task, execute_task, fail_task, retry_task, calculate_retry_delay
from orchestration_engine.models import RetryPolicy, Task, TaskState


def test_ready_task_starts_running(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Executor Test",
        description="Test executor",
        dependencies=[],
        state=TaskState.READY,
        retry_policy=retry_policy,
    )

    result = execute_task(task, conn, 0.0)

    assert result is True
    assert task.state == TaskState.RUNNING


def test_pending_task_is_rejected(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Executor Test",
        description="Test executor",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )

    result = execute_task(task, conn, 0.0)

    assert result is False
    assert task.state == TaskState.PENDING


def test_running_task_can_complete(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Executor Test",
        description="Test executor",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
    )

    result = complete_task(task, conn, 0.0, task_states={})

    assert result is True
    assert task.state == TaskState.SUCCEEDED


def test_ready_task_cannot_complete(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Executor Test",
        description="Test executor",
        dependencies=[],
        state=TaskState.READY,
        retry_policy=retry_policy,
    )

    result = complete_task(task, conn, 0.0, task_states={})

    assert result is False
    assert task.state == TaskState.READY


def test_failed_task_moves_to_retry_wait(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Failure Test",
        description="Test retry behavior",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=1,
    )

    result = fail_task(task, current_time=100.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.RETRY_WAIT
    assert task.next_retry_at == 105.0


def test_failed_task_moves_to_failed_after_last_attempt(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Failure Test",
        description="Test final failure",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=3,
    )

    result = fail_task(task, current_time=100.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.FAILED
    assert task.next_retry_at is None


def test_execute_task_increments_attempt_count(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Attempt Count Test",
        description="Checks attempt count",
        dependencies=[],
        state=TaskState.READY,
        retry_policy=retry_policy,
        attempt_count=0,
    )

    result = execute_task(task, conn, 0.0)

    assert result is True
    assert task.state == TaskState.RUNNING
    assert task.attempt_count == 1


def test_retry_wait_task_becomes_ready(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Retry Test",
        description="Test retry transition",
        dependencies=[],
        state=TaskState.RETRY_WAIT,
        retry_policy=retry_policy,
        attempt_count=1,
        next_retry_at=105.0,
    )

    result = retry_task(task, current_time=105.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.READY
    assert task.attempt_count == 1


def test_second_retry_increments_attempt_count(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-2",
        workflow_id="test-workflow",
        name="Second Retry Test",
        description="Checks second execution attempt",
        dependencies=[],
        state=TaskState.RETRY_WAIT,
        retry_policy=retry_policy,
        attempt_count=1,
        next_retry_at=105.0,
    )

    retry_result = retry_task(task, current_time=105.0, conn=conn, task_states={})
    execute_result = execute_task(task, conn, 105.0)

    assert retry_result is True
    assert execute_result is True
    assert task.state == TaskState.RUNNING
    assert task.attempt_count == 2


def test_retry_task_rejects_non_retry_wait_state(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-3",
        workflow_id="test-workflow",
        name="Invalid Retry Test",
        description="Only RETRY_WAIT tasks can retry",
        dependencies=[],
        state=TaskState.READY,
        retry_policy=retry_policy,
        attempt_count=1,
    )

    result = retry_task(task, current_time=105.0, conn=conn, task_states={})

    assert result is False
    assert task.state == TaskState.READY
    assert task.attempt_count == 1


def test_failed_task_schedules_retry_time(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-4",
        workflow_id="test-workflow",
        name="Retry Delay Test",
        description="Checks retry scheduling time",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=1,
    )

    result = fail_task(task, current_time=105.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.RETRY_WAIT
    assert task.next_retry_at == 110.0


def test_retry_task_rejects_early_retry(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-5",
        workflow_id="test-workflow",
        name="Early Retry Test",
        description="Checks retry cannot happen before scheduled time",
        dependencies=[],
        state=TaskState.RETRY_WAIT,
        retry_policy=retry_policy,
        attempt_count=1,
        next_retry_at=105.0,
    )

    result = retry_task(task, current_time=100.0, conn=conn, task_states={})

    assert result is False
    assert task.state == TaskState.RETRY_WAIT


def test_retry_task_allowed_at_scheduled_time(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-6",
        workflow_id="test-workflow",
        name="Scheduled Retry Test",
        description="Checks retry at scheduled time",
        dependencies=[],
        state=TaskState.RETRY_WAIT,
        retry_policy=retry_policy,
        attempt_count=1,
        next_retry_at=105.0,
    )

    result = retry_task(task, current_time=105.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.READY


def test_calculate_retry_delay() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-7",
        workflow_id="test-workflow",
        name="Retry Delay Calculation",
        description="Checks exponential retry delay",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=1,
    )

    result = calculate_retry_delay(task)

    assert result == 5


def test_calculate_second_retry_delay() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-8",
        workflow_id="test-workflow",
        name="Second Retry Delay",
        description="Checks second retry delay",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=2,
    )

    result = calculate_retry_delay(task)

    assert result == 10


def test_calculate_third_retry_delay() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-9",
        workflow_id="test-workflow",
        name="Third Retry Delay",
        description="Checks third retry delay",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=3,
    )

    result = calculate_retry_delay(task)

    assert result == 20


def test_failed_task_uses_exponential_retry_delay(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-10",
        workflow_id="test-workflow",
        name="Exponential Retry Test",
        description="Checks exponential retry scheduling",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=2,
    )

    result = fail_task(task, current_time=100.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.RETRY_WAIT
    assert task.next_retry_at == 110.0


def test_failed_task_exceeds_max_attempts_goes_to_failed(conn) -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-11",
        workflow_id="test-workflow",
        name="Max Attempts Test",
        description="Checks task fails permanently after max attempts",
        dependencies=[],
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        attempt_count=3,
    )

    result = fail_task(task, current_time=100.0, conn=conn, task_states={})

    assert result is True
    assert task.state == TaskState.FAILED
