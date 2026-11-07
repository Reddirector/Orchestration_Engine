"""Time-Travel Inspection and Deterministic Workflow Replay.

Leverages the append-only SQLite event audit trail to reconstruct workflow states
at any historical step index or timestamp, and fork runs from arbitrary task checkpoints
without re-executing costly upstream computations.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from orchestration_engine.errors import OrchestrationError
from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.models import TaskState, Workflow, WorkflowStatus


def compute_transitive_dependents(workflow: Workflow) -> dict[str, set[str]]:
    """Compute mapping of task_id to all transitive downstream dependent task_ids."""
    direct_dependents: dict[str, set[str]] = {t.task_id: set() for t in workflow.tasks}
    for t in workflow.tasks:
        for dep in t.dependencies:
            if dep in direct_dependents:
                direct_dependents[dep].add(t.task_id)

    transitive: dict[str, set[str]] = {}
    for task in workflow.tasks:
        visited: set[str] = set()
        queue = list(direct_dependents.get(task.task_id, set()))
        while queue:
            curr = queue.pop(0)
            if curr not in visited:
                visited.add(curr)
                queue.extend(direct_dependents.get(curr, set()))
        transitive[task.task_id] = visited

    return transitive


@dataclass(frozen=True)
class WorkflowReplaySnapshot:
    """Historical snapshot of a workflow execution at a specific point in time."""

    run_id: str
    workflow_id: str
    snapshot_step: int
    snapshot_timestamp: float
    task_states: dict[str, str]
    task_attempts: dict[str, int]
    task_outputs: dict[str, Any]
    task_errors: dict[str, str | None]
    workflow_status: str


def time_travel_inspect(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    at_step: int | None = None,
    at_timestamp: float | None = None,
) -> WorkflowReplaySnapshot:
    """Reconstruct the exact state of a workflow run up to a step index or timestamp.

    Args:
        conn: Open SQLite connection.
        run_id: Workflow run identifier.
        at_step: Stop replay after processing this many events (1-indexed).
        at_timestamp: Stop replay after this epoch timestamp.
    """
    cursor = conn.execute(
        """
        SELECT id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count, error
        FROM task_events
        WHERE run_id = ?
        ORDER BY id ASC
        """,
        (run_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        raise OrchestrationError(f"No events found for run_id '{run_id}'")

    workflow_id = rows[0][1]
    task_states: dict[str, str] = {}
    task_attempts: dict[str, int] = {}
    task_errors: dict[str, str | None] = {}
    processed_count = 0
    last_timestamp = rows[0][5]

    for row in rows:
        evt_ts = float(row[5])
        if at_timestamp is not None and evt_ts > at_timestamp:
            break

        processed_count += 1
        last_timestamp = evt_ts
        task_id = row[2]
        new_state = row[4]
        attempt = row[6]
        err = row[7]

        task_states[task_id] = new_state
        task_attempts[task_id] = attempt
        task_errors[task_id] = err

        if at_step is not None and processed_count >= at_step:
            break

    # Fetch outputs for tasks that succeeded up to this replay point
    task_outputs: dict[str, Any] = {}
    succeeded_tasks = [t for t, s in task_states.items() if s == TaskState.SUCCEEDED.value]
    if succeeded_tasks:
        placeholders = ",".join("?" for _ in succeeded_tasks)
        query = (
            f"SELECT task_id, output_json FROM task_outputs "  # noqa: S608
            f"WHERE run_id = ? AND task_id IN ({placeholders})"
        )
        out_cursor = conn.execute(query, (run_id, *succeeded_tasks))
        for t_id, out_raw in out_cursor.fetchall():
            if out_raw is not None:
                try:
                    task_outputs[t_id] = json.loads(out_raw)
                except Exception:
                    task_outputs[t_id] = out_raw

    # Derive overall workflow status
    if any(s == TaskState.FAILED.value for s in task_states.values()):
        wf_status = WorkflowStatus.FAILED.value
    elif all(s == TaskState.SUCCEEDED.value for s in task_states.values()) and task_states:
        wf_status = WorkflowStatus.SUCCEEDED.value
    else:
        wf_status = WorkflowStatus.RUNNING.value

    return WorkflowReplaySnapshot(
        run_id=run_id,
        workflow_id=workflow_id,
        snapshot_step=processed_count,
        snapshot_timestamp=last_timestamp,
        task_states=task_states,
        task_attempts=task_attempts,
        task_outputs=task_outputs,
        task_errors=task_errors,
        workflow_status=wf_status,
    )


def fork_run_from_task(
    conn: sqlite3.Connection,
    source_run_id: str,
    restart_from_task_id: str,
    *,
    new_run_id: str | None = None,
) -> str:
    """Fork an existing run, preserving succeeded upstream outputs while resetting downstream tasks.

    Args:
        conn: Open SQLite connection.
        source_run_id: ID of the run to fork from.
        restart_from_task_id: The task where execution should restart.
        new_run_id: Optional ID for the forked run (defaults to generated UUID).

    Returns:
        The new run_id ready for execution via `resume_run` or `run_workflow`.
    """
    # 1. Fetch source run definition
    cursor = conn.execute(
        "SELECT workflow_id, definition_json FROM runs WHERE run_id = ?",
        (source_run_id,),
    )
    run_row = cursor.fetchone()
    if not run_row:
        raise OrchestrationError(f"Source run '{source_run_id}' not found")

    workflow_id = run_row[0]
    def_json = run_row[1]
    wf = load_workflow_from_json(json.loads(def_json))

    task_ids = {t.task_id for t in wf.tasks}
    if restart_from_task_id not in task_ids:
        raise OrchestrationError(f"Task '{restart_from_task_id}' not in workflow '{workflow_id}'")

    # 2. Determine all downstream tasks that must be invalidated
    dependents = compute_transitive_dependents(wf)
    invalidated_tasks = {restart_from_task_id} | dependents.get(restart_from_task_id, set())

    # 3. Get latest snapshot of source run
    snapshot = time_travel_inspect(conn, source_run_id)

    forked_run_id = new_run_id or uuid.uuid4().hex
    now = time.time()

    with conn:
        # Create new run record
        conn.execute(
            """
            INSERT INTO runs (run_id, workflow_id, started_at, status, definition_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (forked_run_id, workflow_id, now, WorkflowStatus.RUNNING.value, def_json),
        )

        # Copy over valid, non-invalidated upstream task outputs and events
        for task_id, state in snapshot.task_states.items():
            if task_id not in invalidated_tasks and state == TaskState.SUCCEEDED.value:
                # Log inherited success event
                conn.execute(
                    """
                    INSERT INTO task_events (
                        workflow_id, task_id, old_state, new_state, timestamp,
                        attempt_count, run_id, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        task_id,
                        TaskState.PENDING.value,
                        TaskState.SUCCEEDED.value,
                        now,
                        snapshot.task_attempts.get(task_id, 1),
                        forked_run_id,
                        None,
                    ),
                )
                # Copy output if exists
                if task_id in snapshot.task_outputs:
                    out_json = json.dumps(snapshot.task_outputs[task_id])
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO task_outputs (run_id, task_id, output_json, error)
                        VALUES (?, ?, ?, ?)
                        """,
                        (forked_run_id, task_id, out_json, None),
                    )

    return forked_run_id
