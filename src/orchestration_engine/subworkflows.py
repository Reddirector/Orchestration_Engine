"""Hierarchical Sub-Workflows and Nested DAG Execution.

Enables embedding complete child workflows as single steps inside a parent workflow,
with isolated scoped inputs, error bubbling, and hierarchical run tracking.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import (
    Task,
    TaskResult,
    Workflow,
    WorkflowStatus,
)
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow


@dataclasses.dataclass(frozen=True)
class SubWorkflowResult:
    """Result of an embedded child workflow execution."""

    child_run_id: str
    status: WorkflowStatus
    outputs: dict[str, Any]
    error: str | None = None


def _init_subworkflow_tables(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subworkflow_runs (
                parent_run_id TEXT NOT NULL,
                parent_task_id TEXT NOT NULL,
                child_run_id TEXT NOT NULL PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_subworkflow_parent
            ON subworkflow_runs (parent_run_id, parent_task_id)
            """
        )


def execute_subworkflow(
    conn: sqlite3.Connection,
    parent_run_id: str,
    parent_task: Task,
    subworkflow: Workflow,
    task_runner: Callable[[Task], bool | TaskResult],
    *,
    time_source: Callable[[], float] = time.time,
    max_concurrency: int = 1,
) -> TaskResult:
    """Execute a child workflow synchronously on behalf of a parent task.

    Records the parent-child linkage in SQLite, injects parent task inputs
    into child entry tasks, and aggregates child outputs into a TaskResult.
    """
    _init_subworkflow_tables(conn)

    # Propagate parent inputs to root tasks of the subworkflow
    if parent_task.inputs:
        for t in subworkflow.tasks:
            if not t.dependencies:
                # Merge parent inputs into root tasks
                t.inputs.update(parent_task.inputs)

    # Run the child workflow
    child_run_id = run_workflow(
        workflow=subworkflow,
        task_states={t.task_id: t.state for t in subworkflow.tasks},
        time_source=time_source,
        task_runner=task_runner,
        conn=conn,
        max_concurrency=max_concurrency,
    )

    from orchestration_engine.status import get_run_status

    status = get_run_status(conn, child_run_id)

    # Record parent-child linkage
    with conn:
        conn.execute(
            """
            INSERT INTO subworkflow_runs (
                parent_run_id, parent_task_id, child_run_id, workflow_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                parent_run_id,
                parent_task.task_id,
                child_run_id,
                subworkflow.workflow_id,
                status.value,
                time_source(),
            ),
        )

    # Collect outputs of all child tasks
    child_outputs: dict[str, Any] = {}
    cursor = conn.execute(
        "SELECT task_id, output_json, error FROM task_outputs WHERE run_id = ?",
        (child_run_id,),
    )
    import json

    errors: list[str] = []
    for tid, out_json, err in cursor.fetchall():
        if out_json:
            try:
                child_outputs[tid] = json.loads(out_json)
            except Exception:
                child_outputs[tid] = out_json
        if err:
            errors.append(f"Task '{tid}': {err}")

    if status == WorkflowStatus.SUCCEEDED:
        return TaskResult(
            ok=True,
            output={
                "child_run_id": child_run_id,
                "status": status.value,
                "outputs": child_outputs,
            },
        )
    return TaskResult(
        ok=False,
        output={"child_run_id": child_run_id, "status": status.value},
        error=f"Sub-workflow '{subworkflow.workflow_id}' failed ({'; '.join(errors)})",
    )


def make_subworkflow_runner(
    subworkflow: Workflow,
    child_task_runner: Callable[[Task], bool | TaskResult],
    *,
    conn_factory: Callable[[], sqlite3.Connection] | None = None,
    max_concurrency: int = 1,
) -> Callable[[Task], TaskResult]:
    """Create a Task runner function that delegates execution to a child workflow."""

    def runner(task: Task) -> TaskResult:
        # Resolve connection
        conn = conn_factory() if conn_factory else get_connection()
        parent_run = getattr(task, "_run_id", getattr(task, "run_id", "adhoc_parent_run"))
        return execute_subworkflow(
            conn=conn,
            parent_run_id=parent_run,
            parent_task=task,
            subworkflow=subworkflow,
            task_runner=child_task_runner,
            max_concurrency=max_concurrency,
        )

    return runner


def get_subworkflow_tree(conn: sqlite3.Connection, root_run_id: str) -> dict[str, Any]:
    """Inspect and return the full hierarchy of nested sub-workflow runs."""
    _init_subworkflow_tables(conn)

    cursor = conn.execute(
        """
        SELECT parent_task_id, child_run_id, workflow_id, status, created_at
        FROM subworkflow_runs
        WHERE parent_run_id = ?
        ORDER BY created_at ASC
        """,
        (root_run_id,),
    )
    children = []
    for task_id, child_run, wf_id, st, created in cursor.fetchall():
        nested_tree = get_subworkflow_tree(conn, child_run)
        children.append(
            {
                "parent_task_id": task_id,
                "child_run_id": child_run,
                "workflow_id": wf_id,
                "status": st,
                "created_at": created,
                "children": nested_tree.get("children", []),
            }
        )

    return {"run_id": root_run_id, "children": children}
