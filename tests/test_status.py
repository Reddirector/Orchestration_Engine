
from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
from orchestration_engine.status import get_workflow_status


def test_workflow_status_running_while_incomplete() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="In Progress Task",
        description="Still running, not terminal",
        state=TaskState.RUNNING,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-status-running",
        name="Status Running Test",
        description="Checks status is RUNNING while any task is non-terminal",
        tasks=[task],
    )

    assert get_workflow_status(workflow) == WorkflowStatus.RUNNING


def test_workflow_status_succeeded_when_all_tasks_succeed() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task = Task(
        task_id="task-1",
        workflow_id="test-workflow",
        name="Done Task",
        description="Terminal, successful",
        state=TaskState.SUCCEEDED,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-status-succeeded",
        name="Status Succeeded Test",
        description="Checks status is SUCCEEDED when all tasks succeeded",
        tasks=[task],
    )

    assert get_workflow_status(workflow) == WorkflowStatus.SUCCEEDED


def test_workflow_status_failed_when_any_task_failed() -> None:
    retry_policy = RetryPolicy(max_attempts=3, delay_seconds=5)

    task_a = Task(
        task_id="task-a",
        workflow_id="test-workflow",
        name="Failed Task",
        description="Terminal, unsuccessful",
        state=TaskState.FAILED,
        retry_policy=retry_policy,
        dependencies=[],
    )
    task_b = Task(
        task_id="task-b",
        workflow_id="test-workflow",
        name="Succeeded Task",
        description="Terminal, successful, independent branch",
        state=TaskState.SUCCEEDED,
        retry_policy=retry_policy,
        dependencies=[],
    )

    workflow = Workflow(
        workflow_id="workflow-status-failed",
        name="Status Failed Test",
        description="Checks status is FAILED if any task failed, even with others succeeded",
        tasks=[task_a, task_b],
    )

    assert get_workflow_status(workflow) == WorkflowStatus.FAILED
