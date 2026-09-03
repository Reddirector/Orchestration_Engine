from orchestration_engine.models import Task, TaskState, Workflow, WorkflowStatus


def get_workflow_status(workflow: Workflow) -> WorkflowStatus:
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
