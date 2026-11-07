"""Shared Run-Scoped Key-Value Blackboard with Optimistic CAS Memory.

Enables multi-agent AI swarms and tasks across a workflow run to safely share cross-cutting
state, read/write memory, coordinate using optimistic Compare-And-Swap (CAS), and update
atomic counters without race conditions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from orchestration_engine.errors import PersistenceError
from orchestration_engine.persistence import get_connection


class WorkflowBlackboard:
    """Run-scoped transactional Key-Value blackboard with optimistic concurrency control."""

    def __init__(
        self,
        run_id: str,
        db_path: str = "orchestration.db",
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.run_id = run_id
        self.db_path = db_path
        self._conn = conn
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        return get_connection(self.db_path)

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_blackboard (
                        run_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value_json TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (run_id, key)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rb_run_id ON run_blackboard(run_id)"
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to initialize run_blackboard schema: {exc}") from exc
        finally:
            if self._conn is None:
                conn.close()

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key. Returns default if key does not exist."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT value_json FROM run_blackboard WHERE run_id = ? AND key = ?",
                (self.run_id, key),
            )
            row = cursor.fetchone()
            if not row:
                return default
            return json.loads(row[0])
        finally:
            if self._conn is None:
                conn.close()

    def get_with_version(self, key: str) -> tuple[Any, int] | None:
        """Retrieve value and integer version tuple. Returns None if key does not exist."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT value_json, version FROM run_blackboard WHERE run_id = ? AND key = ?",
                (self.run_id, key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return (json.loads(row[0]), int(row[1]))
        finally:
            if self._conn is None:
                conn.close()

    def set(self, key: str, value: Any) -> int:
        """Set a value unconditionally, incrementing its version. Returns the new version."""
        now = time.time()
        val_str = json.dumps(value)
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "SELECT version FROM run_blackboard WHERE run_id = ? AND key = ?",
                    (self.run_id, key),
                )
                row = cursor.fetchone()
                new_ver = (row[0] + 1) if row else 1

                conn.execute(
                    """
                    INSERT INTO run_blackboard (run_id, key, value_json, version, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, key) DO UPDATE SET
                        value_json = excluded.value_json,
                        version = excluded.version,
                        updated_at = excluded.updated_at
                    """,
                    (self.run_id, key, val_str, new_ver, now),
                )
                return new_ver
        finally:
            if self._conn is None:
                conn.close()

    def compare_and_swap(self, key: str, expected_version: int, new_value: Any) -> bool:
        """Perform an atomic Compare-And-Swap.

        If expected_version is 0, succeeds only if the key does NOT currently exist.
        Otherwise, succeeds only if the current version strictly equals expected_version.
        """
        now = time.time()
        val_str = json.dumps(new_value)
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "SELECT version FROM run_blackboard WHERE run_id = ? AND key = ?",
                    (self.run_id, key),
                )
                row = cursor.fetchone()
                curr_ver = row[0] if row else 0

                if curr_ver != expected_version:
                    return False

                new_ver = curr_ver + 1
                if curr_ver == 0:
                    conn.execute(
                        """
                        INSERT INTO run_blackboard (run_id, key, value_json, version, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (self.run_id, key, val_str, new_ver, now),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE run_blackboard
                        SET value_json = ?, version = ?, updated_at = ?
                        WHERE run_id = ? AND key = ? AND version = ?
                        """,
                        (val_str, new_ver, now, self.run_id, key, curr_ver),
                    )
                return True
        finally:
            if self._conn is None:
                conn.close()

    def increment(self, key: str, delta: int = 1) -> int:
        """Atomically increment an integer counter, initializing to delta if not existing."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "SELECT value_json, version FROM run_blackboard WHERE run_id = ? AND key = ?",
                    (self.run_id, key),
                )
                row = cursor.fetchone()
                if row:
                    curr_val = int(json.loads(row[0]))
                    new_val = curr_val + delta
                    new_ver = row[1] + 1
                    conn.execute(
                        """
                        UPDATE run_blackboard
                        SET value_json = ?, version = ?, updated_at = ?
                        WHERE run_id = ? AND key = ?
                        """,
                        (json.dumps(new_val), new_ver, time.time(), self.run_id, key),
                    )
                else:
                    new_val = delta
                    conn.execute(
                        """
                        INSERT INTO run_blackboard (run_id, key, value_json, version, updated_at)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (self.run_id, key, json.dumps(new_val), time.time()),
                    )
                return new_val
        finally:
            if self._conn is None:
                conn.close()

    def delete(self, key: str) -> bool:
        """Delete a key from the blackboard."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM run_blackboard WHERE run_id = ? AND key = ?",
                    (self.run_id, key),
                )
                return cursor.rowcount > 0
        finally:
            if self._conn is None:
                conn.close()

    def list_keys(self) -> list[str]:
        """List all keys stored in this run's blackboard."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT key FROM run_blackboard WHERE run_id = ? ORDER BY key ASC",
                (self.run_id,),
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            if self._conn is None:
                conn.close()

    def dump_state(self) -> dict[str, Any]:
        """Dump all keys and parsed values for this run."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT key, value_json FROM run_blackboard WHERE run_id = ? ORDER BY key ASC",
                (self.run_id,),
            )
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
        finally:
            if self._conn is None:
                conn.close()
