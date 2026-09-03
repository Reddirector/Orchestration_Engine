from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.validation import validate_workflow


def test_invalid_dependency() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        name="Test Task",
        description="Testing invalid dependency",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=["task-99"],
    )

    workflow = Workflow(
        workflow_id="workflow-1",
        name="Invalid Workflow",
        description="Contains a missing dependency",
        tasks=[task],
    )

    assert validate_workflow(workflow) is False


def test_self_dependency() -> None:
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
        workflow_id="workflow-2",
        name="Self Dependency Workflow",
        description="Contains a self dependency",
        tasks=[task],
    )

    assert validate_workflow(workflow) is False


def test_cycle_dependency() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task-A",
        name="Task A",
        description="Task A depends on B",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=["task-B"],
    )

    task_b = Task(
        task_id="task-B",
        name="Task B",
        description="Task B depends on A",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=["task-A"],
    )

    workflow = Workflow(
        workflow_id="workflow-3",
        name="Cycle Workflow",
        description="Contains a dependency cycle",
        tasks=[task_a, task_b],
    )

    assert validate_workflow(workflow) is False


def test_valid_dependency() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_c = Task(
        task_id="task-C",
        name="Task C",
        description="Starting task",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    task_d = Task(
        task_id="task-D",
        name="Task D",
        description="Task D depends on C",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=["task-C"],
    )

    workflow = Workflow(
        workflow_id="workflow-4",
        name="Valid Workflow",
        description="Contains a valid dependency",
        tasks=[task_c, task_d],
    )

    assert validate_workflow(workflow) is True


def test_duplicate_task_ids() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task-1",
        name="Task A",
        description="First task",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    task_b = Task(
        task_id="task-1",
        name="Task B",
        description="Second task with duplicate ID",
        state=TaskState.PENDING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-5",
        name="Duplicate ID Workflow",
        description="Contains duplicate task IDs",
        tasks=[task_a, task_b],
    )

    assert validate_workflow(workflow) is False
