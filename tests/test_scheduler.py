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

    scheduled = schedule_once(workflow, task_states, current_time=0.0)

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

    scheduled = schedule_once(workflow, task_states, current_time=0.0)

    assert task_a not in scheduled
    assert task_b in scheduled
    assert task_b.state == TaskState.READY


def test_schedule_once_retries_ready_task() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)
    task = Task(
        task_id="task-20",
        name="Retry Ready Test",
        description="Checks retry_wait task becomes ready",
        dependencies=[],
        state=TaskState.RETRY_WAIT,
        retry_policy=retry_policy,
        attempt_count=1,
        next_retry_at=100.0,
    )
    workflow = Workflow(
        workflow_id="wf-1",
        name="Test Workflow",
        description="Test",
        tasks=[task],
    )

    schedule_once(
        workflow,
        task_states={"task-20": TaskState.RETRY_WAIT},
        current_time=100.0,
    )

    assert task.state == TaskState.READY


def test_schedule_once_cancels_blocked_tasks() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task_a",
        name="Upstream task",
        description="Fails to trigger cancellation of dependent",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.FAILED,
    )
    task_b = Task(
        task_id="task_b",
        name="Downstream task",
        description="Should be cancelled via schedule_once",
        dependencies=["task_a"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,
    )
    workflow = Workflow(
        workflow_id="wf-schedule-cancel",
        name="Schedule Cancel Test",
        description="Checks schedule_once propagates failure cancellation",
        tasks=[task_a, task_b],
    )

    task_states: dict[str, TaskState] = {
        "task_a": TaskState.FAILED,
        "task_b": TaskState.PENDING,
    }

    # which function under test?
    schedule_once(workflow, task_states, current_time=0.0)

    assert task_b.state == TaskState.CANCELLED
