"""
Deterministic task result caching using SQLite.

Allows caching task outputs based on task identity and input parameters,
avoiding redundant expensive computations and duplicate API requests.
"""

from __future__ import annotations

import functools
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import Task, TaskResult


class TaskCache:
    """
    SQLite-backed deterministic result cache for workflow tasks.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_cache (
                cache_key TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                output_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl_seconds REAL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_task ON task_cache(task_id)"
        )
        self.conn.commit()

    @staticmethod
    def compute_key(task_id: str, inputs: dict[str, Any]) -> str:
        """Compute deterministic SHA-256 hash for task_id and its input dictionary."""
        serialized = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
        raw = f"{task_id}:{serialized}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, task_id: str, inputs: dict[str, Any]) -> tuple[bool, Any]:
        """
        Check if a valid cached output exists for the given task and inputs.

        Returns (True, output_data) on hit, or (False, None) on miss or expiration.
        """
        key = self.compute_key(task_id, inputs)
        now = time.time()
        cursor = self.conn.execute(
            """
            SELECT output_json, created_at, ttl_seconds
            FROM task_cache
            WHERE cache_key = ?
            """,
            (key,),
        )
        row = cursor.fetchone()
        if not row:
            return False, None

        output_json, created_at, ttl = row
        if ttl is not None and (created_at + ttl) < now:
            # Expired
            self.conn.execute("DELETE FROM task_cache WHERE cache_key = ?", (key,))
            self.conn.commit()
            return False, None

        try:
            return True, json.loads(output_json)
        except Exception:
            return True, output_json

    def set(
        self,
        task_id: str,
        inputs: dict[str, Any],
        output: Any,
        ttl_seconds: float | None = None,
    ) -> None:
        """Store task output in the cache."""
        key = self.compute_key(task_id, inputs)
        output_json = json.dumps(output)
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO task_cache (cache_key, task_id, output_json, created_at, ttl_seconds)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                output_json = excluded.output_json,
                created_at = excluded.created_at,
                ttl_seconds = excluded.ttl_seconds
            """,
            (key, task_id, output_json, now, ttl_seconds),
        )
        self.conn.commit()

    def clear(self) -> None:
        """Clear all cached entries."""
        self.conn.execute("DELETE FROM task_cache")
        self.conn.commit()

    def wrap_runner(
        self,
        runner: Callable[[Task], bool | TaskResult],
        ttl_seconds: float | None = None,
    ) -> Callable[[Task], TaskResult]:
        """Wrap a task runner callable to automatically intercept and cache outputs."""
        @functools.wraps(runner)
        def cached_runner(task: Task) -> TaskResult:
            hit, cached_val = self.get(task.task_id, task.inputs)
            if hit:
                return TaskResult(ok=True, output=cached_val)

            res = runner(task)
            if isinstance(res, TaskResult):
                if res.ok and res.output is not None:
                    self.set(task.task_id, task.inputs, res.output, ttl_seconds=ttl_seconds)
                return res
            elif res:
                return TaskResult(ok=True)
            return TaskResult(ok=False)

        return cached_runner
