from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow


def test_pending_state() -> None:
    assert TaskState.PENDING.value == "pending"


def test_task_creation() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="counting the sec",
        description="A counting task",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )
    assert task.task_id == "task-1"
    assert task.state == TaskState.PENDING
    assert task.retry_policy.max_attempts == 3
    assert task.retry_policy.delay_seconds == 5


def test_workflow() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task1 = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Task 1",
        description="First task",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )

    task2 = Task(
        task_id="task-2",
        workflow_id="test-workflow",
        name="Task 2",
        description="Second task",
        dependencies=["task-1"],
        state=TaskState.PENDING,
        retry_policy=retry_policy,
    )

    workflow = Workflow(
        workflow_id="workflow-1",
        name="Example Workflow",
        description="A workflow with two tasks",
        tasks=[task1, task2],

    )

    assert workflow.workflow_id == "workflow-1"
    assert len(workflow.tasks) == 2
    assert workflow.tasks[0].task_id == "task-1"
    assert task2.dependencies == ["task-1"]
