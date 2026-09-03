from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.readiness import get_ready_tasks, is_task_ready, mark_ready_tasks, cancel_blocked_tasks


def test_task_with_no_dependencies_is_ready() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        name="Dependies check",
        task_id="check-1",
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
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_j = Task(
        name="Dependies check",
        task_id="check-5",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_l = Task(
        name="Dependies check",
        task_id="check-6",
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
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_j = Task(
        name="Dependies check",
        task_id="check-5",
        dependencies=[],
        description="first check",
        retry_policy=retry_policy,
        state=TaskState.PENDING,

    )
    task_l = Task(
        name="Dependies check",
        task_id="check-6",
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


def test_mark_ready_task() -> None:
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
    marked = mark_ready_tasks(workflow, task_states)
    assert task_a.state == TaskState.READY
    assert task_states["task_a"] == TaskState.READY
    assert task_b.state == TaskState.PENDING
    assert task_a in marked
    assert task_b not in marked


def test_task_becomes_ready_after_dependency_succeeds() -> None:
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
    task_a.state = TaskState.SUCCEEDED
    task_states["task_a"] = TaskState.SUCCEEDED
    marked = mark_ready_tasks(workflow, task_states)

    assert task_b.state == TaskState.READY
    assert task_states["task_b"] == TaskState.READY
    assert task_b in marked


def test_dependent_task_cancelled_when_dependency_failed() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task_a",
        name="Upstream task",
        description="Fails to trigger cancellation of dependent",
        dependencies=[],
        retry_policy=retry_policy,
        state=TaskState.FAILED,  # what state represents "this task is done and unsuccessful"?
    )
    task_b = Task(
        task_id="task_b",
        name="Downstream task",
        description="Should be cancelled since its dependency failed",
        dependencies=["task_a"],
        retry_policy=retry_policy,
        state=TaskState.PENDING,  # what state is task_b in before scheduling runs?
    )
    workflow = Workflow(
        workflow_id="wf-fail-propagation",
        name="Failure Propagation Test",
        description="Checks that dependents get cancelled on upstream failure",
        tasks=[task_a, task_b],
    )

    task_states: dict[str, TaskState] = {
        # must mirror task_a.state — this dict is the "external view" is_task_ready() reads
        "task_a": TaskState.FAILED,
        "task_b": TaskState.PENDING,
    }

    # which function should run this check — existing one, or a new one you need to write?
    cancel_blocked_tasks(workflow, task_states)

    # the state that should represent "unreachable because a dependency failed"
    assert task_b.state == TaskState.CANCELLED
