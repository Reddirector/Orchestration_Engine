from orchestration_engine.models import TaskState, Workflow, WorkflowStatus


def get_workflow_status(workflow: Workflow) -> WorkflowStatus:
    """
    Determine a workflow's overall status from its tasks' current states.

    Reads task.state directly off the Task objects inside the given Workflow —
    it does not query the database. Pass the same Workflow instance that
    run_workflow (or run_workflow_from_file) mutated; a freshly reloaded or
    stale copy will not reflect real progress.

    Returns RUNNING if any task is still pending, ready, running, or waiting
    to retry. Otherwise returns FAILED if any task failed or was cancelled,
    and SUCCEEDED only if every task succeeded.
    """
    for task in workflow.tasks:
        if task.state in (
            TaskState.PENDING,
            TaskState.READY,
            TaskState.RUNNING,
            TaskState.RETRY_WAIT,
        ):
            return WorkflowStatus.RUNNING

    for task in workflow.tasks:
        if task.state in (TaskState.FAILED, TaskState.CANCELLED):
            return WorkflowStatus.FAILED

    return WorkflowStatus.SUCCEEDED
