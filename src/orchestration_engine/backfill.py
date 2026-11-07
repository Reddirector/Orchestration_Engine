"""
Historical Backfill & Deterministic Catchup Engine for Orchestration Engine.

Enables automated and controlled historical backfilling across time ranges,
with deterministic interval slicing, catch-up policies, anti-thundering-herd jitter,
and execution record tracking.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from orchestration_engine.models import Task, TaskResult, TaskState, Workflow, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_run_status


class CatchupPolicy(StrEnum):
    """Execution policy for handling past scheduled intervals."""

    ALL = "ALL"
    LATEST_ONLY = "LATEST_ONLY"
    SLIDING_WINDOW = "SLIDING_WINDOW"


@dataclass
class BackfillWindow:
    """Represents a discrete temporal slice for workflow backfill execution."""

    window_id: str
    start_time: float
    end_time: float
    jitter_seconds: float = 0.0
    status: str = "PENDING"
    run_id: str | None = None


@dataclass
class BackfillPlan:
    """A compiled backfill execution plan containing discrete time windows."""

    workflow_id: str
    windows: list[BackfillWindow]
    catchup_policy: CatchupPolicy


def generate_backfill_plan(
    workflow_id: str,
    start_time: float,
    end_time: float,
    interval_seconds: float,
    catchup_policy: CatchupPolicy = CatchupPolicy.ALL,
    jitter_max_seconds: float = 0.0,
    sliding_window_count: int = 5,
) -> BackfillPlan:
    """Compile a deterministic backfill plan across a historical time window."""
    if end_time < start_time:
        raise ValueError("end_time must be greater than or equal to start_time")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    raw_windows: list[tuple[float, float]] = []
    curr = start_time
    idx = 0
    while curr < end_time:
        next_curr = min(curr + interval_seconds, end_time)
        raw_windows.append((curr, next_curr))
        curr = next_curr
        idx += 1

    if not raw_windows and start_time == end_time:
        raw_windows.append((start_time, end_time))

    if catchup_policy == CatchupPolicy.LATEST_ONLY:
        raw_windows = raw_windows[-1:] if raw_windows else []
    elif catchup_policy == CatchupPolicy.SLIDING_WINDOW:
        raw_windows = raw_windows[-sliding_window_count:]

    windows: list[BackfillWindow] = []
    for i, (w_start, w_end) in enumerate(raw_windows):
        wid = f"w_{int(w_start)}_{int(w_end)}_{i}"
        jitter = 0.0
        if jitter_max_seconds > 0.0:
            # Deterministic pseudo-random jitter based on workflow_id and window_id
            h = int(
                hashlib.sha256(f"{workflow_id}:{wid}".encode()).hexdigest()[:8],
                16,
            )
            jitter = (h % 1000) / 1000.0 * jitter_max_seconds

        windows.append(
            BackfillWindow(
                window_id=wid,
                start_time=w_start,
                end_time=w_end,
                jitter_seconds=round(jitter, 3),
            )
        )

    return BackfillPlan(
        workflow_id=workflow_id,
        windows=windows,
        catchup_policy=catchup_policy,
    )


class BackfillExecutor:
    """Executes compiled backfill plans while logging progress in SQLite."""

    def __init__(self, conn_or_path: sqlite3.Connection | str | None = None) -> None:
        if conn_or_path is None or conn_or_path == ":memory:":
            self._db_path: str | None = None
            self._conn: sqlite3.Connection | None = get_connection(":memory:")
        elif isinstance(conn_or_path, str):
            self._db_path = conn_or_path
            self._conn = None
        else:
            self._db_path = None
            self._conn = conn_or_path

        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._db_path is not None:
            return get_connection(self._db_path)
        raise RuntimeError("BackfillExecutor has no connection or db_path configured.")

    def _init_tables(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backfill_runs (
                    backfill_id TEXT NOT NULL,
                    window_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    run_id TEXT,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def run_plan(
        self,
        plan: BackfillPlan,
        workflow: Workflow,
        task_runner: Callable[[Task], bool | TaskResult],
        conn_factory: Callable[[], sqlite3.Connection] | None = None,
        backfill_id: str | None = None,
    ) -> list[BackfillWindow]:
        """Execute all windows in a backfill plan sequentially."""
        bid = backfill_id or f"bf_{int(time.time())}"
        conn = self._get_conn()

        for win in plan.windows:
            win.status = "RUNNING"
            now = time.time()
            with conn:
                conn.execute(
                    """
                    INSERT INTO backfill_runs (
                        backfill_id, window_id, workflow_id,
                        start_time, end_time, run_id, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?)
                    ON CONFLICT(window_id) DO UPDATE SET
                        status = 'RUNNING', updated_at = excluded.updated_at
                    """,
                    (
                        bid,
                        win.window_id,
                        plan.workflow_id,
                        win.start_time,
                        win.end_time,
                        win.run_id,
                        now,
                    ),
                )

            # Reset task states and inject window bounds for the run
            task_states = {}
            for t in workflow.tasks:
                t.state = TaskState.PENDING
                task_states[t.task_id] = TaskState.PENDING
                t.inputs["window_start"] = win.start_time
                t.inputs["window_end"] = win.end_time
                t.inputs["window_id"] = win.window_id

            wf_conn = conn_factory() if conn_factory else conn
            run_id = run_workflow(
                workflow=workflow,
                task_states=task_states,
                time_source=time.time,
                task_runner=task_runner,
                conn=wf_conn,
            )

            status = get_run_status(wf_conn, run_id)
            win.run_id = run_id
            win.status = "SUCCEEDED" if status == WorkflowStatus.SUCCEEDED else "FAILED"

            with conn:
                conn.execute(
                    """
                    UPDATE backfill_runs
                    SET run_id = ?, status = ?, updated_at = ?
                    WHERE window_id = ?
                    """,
                    (run_id, win.status, time.time(), win.window_id),
                )

        return plan.windows

    def get_window_status(self, window_id: str) -> dict[str, str] | None:
        """Query execution status of a specific window."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT window_id, run_id, status FROM backfill_runs WHERE window_id = ?",
            (window_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {"window_id": row[0], "run_id": row[1], "status": row[2]}
