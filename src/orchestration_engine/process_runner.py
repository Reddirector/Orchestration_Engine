"""
Multiprocess Workflow Runner for CPU-bound tasks.

Bypasses the Python Global Interpreter Lock (GIL) by executing workflow tasks
across separate OS worker processes using Python's standard multiprocessing.
Zero external runtime dependencies.
"""

from __future__ import annotations

import os
import pickle
import sqlite3
import time
from collections.abc import Callable

from orchestration_engine.errors import WorkflowValidationError
from orchestration_engine.models import Hooks, Task, TaskResult, Workflow
from orchestration_engine.runner import run_workflow


def run_workflow_multiprocess(
    workflow: Workflow,
    task_runner: Callable[[Task], bool | TaskResult],
    conn: sqlite3.Connection | None = None,
    max_concurrency: int | None = None,
    time_source: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    run_id: str | None = None,
    hooks: Hooks | None = None,
) -> str:
    """
    Execute a Workflow across multiple CPU processes to bypass Python GIL contention.

    Args:
        workflow: The Workflow DAG to execute.
        task_runner: Picklable callable invoked for each task.
        conn: Optional SQLite connection; if omitted, an in-memory DB is used.
        max_concurrency: Maximum worker processes (defaults to os.cpu_count() or 2).
        time_source: Function returning current epoch seconds.
        sleep: Sleep function for retry delays.
        run_id: Optional existing run ID to resume.
        hooks: Optional lifecycle event hooks.

    Returns:
        The run_id string.
    """
    # Verify picklability upfront with clear error messages
    try:
        pickle.dumps(task_runner)
    except Exception as exc:
        raise WorkflowValidationError(
            f"task_runner must be picklable to run in multi-process mode: {exc}"
        ) from exc

    effective_concurrency = max_concurrency
    if effective_concurrency is None:
        effective_concurrency = max(1, os.cpu_count() or 2)

    should_close = False
    if conn is None:
        from orchestration_engine.persistence import get_connection

        conn = get_connection(":memory:")
        should_close = True

    try:
        return run_workflow(
            workflow=workflow,
            task_states={},
            time_source=time_source,
            task_runner=task_runner,
            conn=conn,
            sleep=sleep,
            run_id=run_id,
            max_concurrency=effective_concurrency,
            executor="process",
            hooks=hooks,
        )
    finally:
        if should_close:
            conn.close()
