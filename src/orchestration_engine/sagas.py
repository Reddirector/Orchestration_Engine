"""Distributed Sagas and Compensating Transactions.

Implements the Saga pattern for multi-step distributed operations (e.g., fintech,
order processing, cloud resource provisioning) where transactions cannot be executed
in a single database transaction. If any step fails or times out, compensations
(undo actions) are automatically executed in reverse order for all tasks that
previously succeeded.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from orchestration_engine.models import Task, TaskResult, TaskState, Workflow, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_workflow_status

logger = logging.getLogger(__name__)


class SagaStatus(StrEnum):
    """Execution status of a Saga transaction."""

    COMPLETED = "completed"
    COMPENSATED = "compensated"
    COMPENSATION_FAILED = "compensation_failed"


@dataclasses.dataclass(frozen=True)
class SagaResult:
    """Result of executing a Saga workflow with compensation support."""

    status: SagaStatus
    workflow_run_id: str
    workflow_status: WorkflowStatus
    compensated_tasks: list[str] = dataclasses.field(default_factory=list)
    compensation_errors: dict[str, str] = dataclasses.field(default_factory=dict)


def _init_saga_tables(conn: sqlite3.Connection) -> None:
    """Ensure the saga_compensations audit table exists."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saga_compensations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at REAL NOT NULL,
                completed_at REAL,
                error TEXT,
                output_json TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_saga_run ON saga_compensations(run_id)"
        )


def run_saga(
    workflow: Workflow,
    task_runner: dict[str, Callable[..., Any]] | Callable[[Task], Any],
    compensators: dict[str, Callable[..., Any]],
    *,
    db_path: str = "orchestration.db",
    max_concurrency: int = 4,
    inputs: dict[str, Any] | None = None,
    time_source: Callable[[], float] = time.time,
) -> SagaResult:
    """Execute a workflow as a distributed Saga.

    If any task in the workflow fails or the workflow status is not SUCCEEDED,
    all previously completed tasks that have a registered compensator are
    executed in reverse topological order to roll back state.

    Args:
        workflow: The workflow definition to execute.
        task_runner: Mapping of task_id to its forward execution callable, or a runner function.
        compensators: Mapping of task_id to its backward compensation callable.
            The callable can optionally accept ``(task_id, output, inputs)``.
        db_path: Path to the SQLite state database.
        max_concurrency: Maximum worker concurrency for forward execution.
        inputs: Global inputs passed to the workflow.
        time_source: Time function for audit timestamps.

    Returns:
        SagaResult indicating whether the workflow completed or was compensated.
    """
    conn = get_connection(db_path)
    _init_saga_tables(conn)

    run_id = uuid.uuid4().hex

    # Adapt dict or callable
    if isinstance(task_runner, dict):
        runner_map = task_runner

        def _unified_runner(task: Task) -> TaskResult:
            fn = runner_map.get(task.task_id)
            if fn is None:
                return TaskResult(ok=True)
            try:
                out = fn(**task.inputs)
            except TypeError:
                try:
                    out = fn(task.inputs)
                except TypeError:
                    out = fn()
            return TaskResult(ok=True, output=out)

        active_runner: Callable[[Task], Any] = _unified_runner
    else:
        active_runner = task_runner

    # 1. Run forward workflow
    task_states: dict[str, TaskState] = {}
    actual_run_id = run_workflow(
        workflow,
        task_states=task_states,
        time_source=time_source,
        task_runner=active_runner,
        conn=conn,
        max_concurrency=max_concurrency,
        run_id=run_id,
    )

    wf_status = get_workflow_status(workflow)

    # If all tasks succeeded, the saga is complete
    if wf_status == WorkflowStatus.SUCCEEDED:
        return SagaResult(
            status=SagaStatus.COMPLETED,
            workflow_run_id=actual_run_id,
            workflow_status=wf_status,
            compensated_tasks=[],
            compensation_errors={},
        )

    # 2. Workflow failed -> Determine which tasks completed successfully
    # Read outputs from SQLite
    task_outputs: dict[str, Any] = {}
    with conn:
        cursor = conn.execute(
            "SELECT task_id, output_json FROM task_outputs WHERE run_id = ?",
            (actual_run_id,),
        )
        for row in cursor.fetchall():
            task_outputs[row[0]] = row[1]

    # Topological order of tasks
    completed_task_ids = [
        tid for tid, state in task_states.items() if state == TaskState.SUCCEEDED
    ]

    # Sort completed tasks in reverse execution order
    ordered_task_ids = [t.task_id for t in workflow.tasks]
    reversed_completed = [
        tid for tid in reversed(ordered_task_ids) if tid in completed_task_ids
    ]

    compensated_tasks: list[str] = []
    compensation_errors: dict[str, str] = {}

    for tid in reversed_completed:
        comp_fn = compensators.get(tid)
        if comp_fn is None:
            continue

        started_at = time_source()
        with conn:
            conn.execute(
                """
                INSERT INTO saga_compensations (run_id, task_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (actual_run_id, tid, started_at),
            )

        try:
            task_out = task_outputs.get(tid)
            try:
                comp_fn(task_output=task_out, run_id=actual_run_id)
            except TypeError:
                try:
                    comp_fn(task_out)
                except TypeError:
                    comp_fn()

            completed_at = time_source()
            with conn:
                conn.execute(
                    """
                    UPDATE saga_compensations
                    SET status = 'succeeded', completed_at = ?
                    WHERE run_id = ? AND task_id = ?
                    """,
                    (completed_at, actual_run_id, tid),
                )
            compensated_tasks.append(tid)
        except Exception as exc:
            err_msg = str(exc)
            compensation_errors[tid] = err_msg
            completed_at = time_source()
            logger.error("Saga compensation failed for task '%s': %s", tid, err_msg)
            with conn:
                conn.execute(
                    """
                    UPDATE saga_compensations
                    SET status = 'failed', completed_at = ?, error = ?
                    WHERE run_id = ? AND task_id = ?
                    """,
                    (completed_at, err_msg, actual_run_id, tid),
                )

    saga_status = (
        SagaStatus.COMPENSATION_FAILED
        if compensation_errors
        else SagaStatus.COMPENSATED
    )

    return SagaResult(
        status=saga_status,
        workflow_run_id=actual_run_id,
        workflow_status=wf_status,
        compensated_tasks=compensated_tasks,
        compensation_errors=compensation_errors,
    )
