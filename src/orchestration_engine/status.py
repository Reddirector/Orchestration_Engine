import json
import sqlite3

from orchestration_engine.errors import OrchestrationError
from orchestration_engine.models import TaskState, Workflow, WorkflowStatus
from orchestration_engine.persistence import _migrate_database


def get_workflow_status(workflow: Workflow) -> WorkflowStatus:
    """
    Determine a workflow's overall status from its tasks' in-memory states.

    Reads task.state directly off the Task objects inside the given Workflow —
    it is strictly IN-MEMORY and does not query the database. Pass the same Workflow
    instance that run_workflow (or run_workflow_from_file) mutated; a freshly
    reloaded or stale copy will not reflect real progress.

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


def get_run_status(conn: sqlite3.Connection, run_id: str) -> WorkflowStatus:
    """
    Derive the current WorkflowStatus of a run directly from the database
    by inspecting the latest recorded state of each task in the workflow.
    Raises OrchestrationError if the run_id is not found.
    """
    _migrate_database(conn)
    cursor = conn.execute(
        "SELECT definition_json FROM runs WHERE run_id = ?",
        (run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise OrchestrationError(f"Run {run_id!r} not found in database")

    definition_json = row[0]
    data = json.loads(definition_json)
    task_ids = [t["task_id"] for t in data.get("tasks", [])]

    cursor = conn.execute(
        """
        SELECT task_id, new_state
        FROM task_events
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    )
    latest_states: dict[str, TaskState] = {}
    for task_id, new_state in cursor.fetchall():
        latest_states[task_id] = TaskState(new_state)

    for tid in task_ids:
        state = latest_states.get(tid, TaskState.PENDING)
        if state in (
            TaskState.PENDING,
            TaskState.READY,
            TaskState.RUNNING,
            TaskState.RETRY_WAIT,
        ):
            return WorkflowStatus.RUNNING

    for tid in task_ids:
        state = latest_states.get(tid, TaskState.PENDING)
        if state in (TaskState.FAILED, TaskState.CANCELLED):
            return WorkflowStatus.FAILED

    return WorkflowStatus.SUCCEEDED
