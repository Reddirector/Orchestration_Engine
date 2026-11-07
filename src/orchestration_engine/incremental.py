"""Incremental DAG Evaluation and Content-Addressable Task Execution.

Provides 'make'-style and 'bazel'-style incremental build intelligence for workflows:
skips re-executing tasks if their code fingerprint, explicit inputs, and upstream
dependency outputs have not changed since the last execution.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import Task, TaskResult
from orchestration_engine.persistence import get_connection


@dataclasses.dataclass(frozen=True)
class IncrementalRunResult:
    """Summary of tasks skipped vs executed in an incremental workflow pass."""

    skipped_task_ids: list[str]
    executed_task_ids: list[str]


def compute_task_hash(
    task: Task,
    code_fingerprint: str | None = None,
    upstream_outputs: dict[str, Any] | None = None,
) -> str:
    """Compute a deterministic 16-character SHA-256 hash for a task.

    Incorporates the task_id, explicit inputs, upstream dependency outputs,
    and optional code fingerprint.
    """
    hasher = hashlib.sha256()
    hasher.update(task.task_id.encode("utf-8"))

    if code_fingerprint:
        hasher.update(code_fingerprint.encode("utf-8"))

    # Inputs
    inputs_payload = task.inputs if upstream_outputs is None else upstream_outputs
    try:
        norm_inputs = json.dumps(inputs_payload, sort_keys=True, default=str)
    except Exception:
        norm_inputs = str(inputs_payload)
    hasher.update(norm_inputs.encode("utf-8"))

    return hasher.hexdigest()[:16]


class IncrementalStore:
    """SQLite-backed cache for incremental task output reuse."""

    def __init__(self, conn_or_path: sqlite3.Connection | str) -> None:
        if isinstance(conn_or_path, str):
            self.db_path: str | None = conn_or_path
            self._conn: sqlite3.Connection | None = None
        else:
            self.db_path = None
            self._conn = conn_or_path
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path is not None:
            return get_connection(self.db_path)
        assert self._conn is not None
        return self._conn

    def _init_tables(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incremental_task_cache (
                    task_hash TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    output_json TEXT,
                    executed_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_incremental_task
                ON incremental_task_cache (task_id)
                """
            )

    def get(self, task_hash: str) -> Any | None:
        """Retrieve cached output if task_hash exists, else None."""
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                "SELECT output_json FROM incremental_task_cache WHERE task_hash = ?",
                (task_hash,),
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return row[0]

    def has(self, task_hash: str) -> bool:
        """Check if a task_hash is already present in cache."""
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                "SELECT 1 FROM incremental_task_cache WHERE task_hash = ?",
                (task_hash,),
            )
            return cursor.fetchone() is not None

    def put(self, task_hash: str, task_id: str, output: Any) -> None:
        """Persist output under task_hash."""
        try:
            out_json = json.dumps(output, sort_keys=True, default=str)
        except Exception:
            out_json = json.dumps(str(output))

        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incremental_task_cache (
                    task_hash, task_id, output_json, executed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (task_hash, task_id, out_json, time.time()),
            )

    def invalidate(self, task_id: str | None = None) -> int:
        """Clear cache entries for a specific task_id, or all entries if None."""
        conn = self._get_conn()
        with conn:
            if task_id is None:
                cursor = conn.execute("DELETE FROM incremental_task_cache")
            else:
                cursor = conn.execute(
                    "DELETE FROM incremental_task_cache WHERE task_id = ?",
                    (task_id,),
                )
            return cursor.rowcount


def wrap_incremental(
    store: IncrementalStore,
    runner: Callable[[Task], bool | TaskResult],
    code_fingerprints: dict[str, str] | None = None,
) -> tuple[Callable[[Task], TaskResult], Callable[[], IncrementalRunResult]]:
    """Wrap a task runner with incremental execution memoization.

    Returns:
        (wrapped_runner, get_run_summary_fn)
    """
    fingerprints = code_fingerprints or {}
    skipped: list[str] = []
    executed: list[str] = []

    def wrapped_runner(task: Task) -> TaskResult:
        fp = fingerprints.get(task.task_id)
        task_hash = compute_task_hash(task, code_fingerprint=fp)

        # Check if already cached
        if store.has(task_hash):
            cached_out = store.get(task_hash)
            skipped.append(task.task_id)
            return TaskResult(
                ok=True,
                output=cached_out,
            )

        # Execute
        res = runner(task)
        if isinstance(res, TaskResult):
            if res.ok:
                store.put(task_hash, task.task_id, res.output)
            executed.append(task.task_id)
            return res
        if bool(res):
            store.put(task_hash, task.task_id, None)
            executed.append(task.task_id)
            return TaskResult(ok=True)

        executed.append(task.task_id)
        return TaskResult(ok=False, error=f"Task '{task.task_id}' returned False")

    def get_summary() -> IncrementalRunResult:
        return IncrementalRunResult(
            skipped_task_ids=list(skipped),
            executed_task_ids=list(executed),
        )

    return wrapped_runner, get_summary
