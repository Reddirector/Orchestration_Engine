"""
Distributed Work Stealing & Dead Worker Reclamation for Orchestration Engine.

Enables multi-worker clusters to dynamically balance task distribution by allowing
under-utilized workers to steal ready tasks from overloaded peers, while automatically
reclaiming orphaned tasks from dead or non-responsive worker nodes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field

from orchestration_engine.persistence import get_connection


@dataclass
class WorkerNodeInfo:
    """Represents the registration and heartbeat state of a cluster worker node."""

    worker_id: str
    capacity: int = 4
    active_tasks: list[str] = field(default_factory=list)
    last_heartbeat: float = 0.0
    status: str = "ALIVE"  # "ALIVE", "DRAINING", "DEAD"
    host: str = "127.0.0.1"
    port: int = 0


class WorkStealingRegistry:
    """SQLite-backed coordinator registry managing worker load, stealing, and reclamation."""

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
        raise RuntimeError("WorkStealingRegistry has no connection or database path configured.")

    def _init_tables(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stealing_workers (
                    worker_id TEXT PRIMARY KEY,
                    capacity INTEGER NOT NULL,
                    active_tasks_json TEXT NOT NULL,
                    last_heartbeat REAL NOT NULL,
                    status TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stealing_tasks (
                    task_id TEXT PRIMARY KEY,
                    assigned_worker_id TEXT,
                    state TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_stealing_tasks_worker
                ON stealing_tasks (assigned_worker_id, state)
                """
            )

    def register_worker(
        self,
        worker_id: str,
        capacity: int = 4,
        host: str = "127.0.0.1",
        port: int = 0,
        time_source: float | None = None,
    ) -> None:
        """Register or update a worker node in the cluster."""
        now = time.time() if time_source is None else time_source
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO stealing_workers (
                    worker_id, capacity, active_tasks_json, last_heartbeat, status, host, port
                ) VALUES (?, ?, ?, ?, 'ALIVE', ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    capacity = excluded.capacity,
                    last_heartbeat = excluded.last_heartbeat,
                    status = 'ALIVE',
                    host = excluded.host,
                    port = excluded.port
                """,
                (worker_id, capacity, json.dumps([]), now, host, port),
            )

    def heartbeat(
        self,
        worker_id: str,
        active_tasks: list[str] | None = None,
        time_source: float | None = None,
    ) -> None:
        """Record a heartbeat timestamp and update active task list for a worker."""
        now = time.time() if time_source is None else time_source
        tasks_json = json.dumps(active_tasks or [])
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                UPDATE stealing_workers
                SET last_heartbeat = ?, active_tasks_json = ?, status = 'ALIVE'
                WHERE worker_id = ?
                """,
                (now, tasks_json, worker_id),
            )

    def enqueue_task(
        self,
        task_id: str,
        assigned_worker_id: str | None = None,
        state: str = "READY",
        time_source: float | None = None,
    ) -> None:
        """Enqueue a task into the cluster, optionally pre-assigning it to a worker."""
        now = time.time() if time_source is None else time_source
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO stealing_tasks (task_id, assigned_worker_id, state, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    assigned_worker_id = excluded.assigned_worker_id,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (task_id, assigned_worker_id, state, now),
            )

    def steal_work(
        self,
        thief_worker_id: str,
        max_tasks: int = 1,
        time_source: float | None = None,
    ) -> list[str]:
        """Attempt to steal up to `max_tasks` ready tasks from the most loaded peer worker.

        First checks for unassigned ready tasks; if none, identifies peer workers
        with the highest queued load and reassigns ready tasks to the thief.
        """
        now = time.time() if time_source is None else time_source
        conn = self._get_conn()

        with conn:
            # 1. Grab unassigned ready tasks first if available
            cursor = conn.execute(
                """
                SELECT task_id FROM stealing_tasks
                WHERE assigned_worker_id IS NULL AND state = 'READY'
                ORDER BY updated_at ASC LIMIT ?
                """,
                (max_tasks,),
            )
            unassigned = [row[0] for row in cursor.fetchall()]
            if unassigned:
                for tid in unassigned:
                    conn.execute(
                        """
                        UPDATE stealing_tasks
                        SET assigned_worker_id = ?, updated_at = ?
                        WHERE task_id = ?
                        """,
                        (thief_worker_id, now, tid),
                    )
                return unassigned

            # 2. Identify overloaded peer worker with the most ready tasks
            cursor = conn.execute(
                """
                SELECT t.assigned_worker_id, COUNT(*) as cnt
                FROM stealing_tasks t
                JOIN stealing_workers w ON t.assigned_worker_id = w.worker_id
                WHERE t.assigned_worker_id != ? AND t.state = 'READY' AND w.status = 'ALIVE'
                GROUP BY t.assigned_worker_id
                ORDER BY cnt DESC LIMIT 1
                """,
                (thief_worker_id,),
            )
            row = cursor.fetchone()
            if not row or row[1] <= 1:
                # No peer has spare backlog to steal
                return []

            victim_worker_id = row[0]
            stealable_count = min(max_tasks, row[1] // 2 or 1)

            cursor = conn.execute(
                """
                SELECT task_id FROM stealing_tasks
                WHERE assigned_worker_id = ? AND state = 'READY'
                ORDER BY updated_at DESC LIMIT ?
                """,
                (victim_worker_id, stealable_count),
            )
            stolen_ids = [r[0] for r in cursor.fetchall()]
            for tid in stolen_ids:
                conn.execute(
                    """
                    UPDATE stealing_tasks
                    SET assigned_worker_id = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (thief_worker_id, now, tid),
                )

            return stolen_ids

    def reclaim_dead_workers(
        self,
        timeout_seconds: float = 30.0,
        time_source: float | None = None,
    ) -> list[str]:
        """Detect worker nodes that stopped heartbeating, mark DEAD, and reclaim their tasks."""
        now = time.time() if time_source is None else time_source
        deadline = now - timeout_seconds
        conn = self._get_conn()

        reclaimed_tasks: list[str] = []
        with conn:
            cursor = conn.execute(
                """
                SELECT worker_id FROM stealing_workers
                WHERE status = 'ALIVE' AND last_heartbeat < ?
                """,
                (deadline,),
            )
            dead_workers = [r[0] for r in cursor.fetchall()]

            for wid in dead_workers:
                conn.execute(
                    "UPDATE stealing_workers SET status = 'DEAD' WHERE worker_id = ?",
                    (wid,),
                )
                cursor = conn.execute(
                    """
                    SELECT task_id FROM stealing_tasks
                    WHERE assigned_worker_id = ? AND state NOT IN ('SUCCEEDED', 'FAILED')
                    """,
                    (wid,),
                )
                tids = [r[0] for r in cursor.fetchall()]
                for tid in tids:
                    conn.execute(
                        """
                        UPDATE stealing_tasks
                        SET assigned_worker_id = NULL, state = 'READY', updated_at = ?
                        WHERE task_id = ?
                        """,
                        (now, tid),
                    )
                reclaimed_tasks.extend(tids)

        return reclaimed_tasks

    def get_worker(self, worker_id: str) -> WorkerNodeInfo | None:
        """Fetch node details for a specific worker."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT worker_id, capacity, active_tasks_json, last_heartbeat, status, host, port
            FROM stealing_workers WHERE worker_id = ?
            """,
            (worker_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return WorkerNodeInfo(
            worker_id=row[0],
            capacity=row[1],
            active_tasks=json.loads(row[2]),
            last_heartbeat=row[3],
            status=row[4],
            host=row[5],
            port=row[6],
        )

    def get_workers(self) -> list[WorkerNodeInfo]:
        """List all registered workers in the cluster."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT worker_id, capacity, active_tasks_json, last_heartbeat, status, host, port
            FROM stealing_workers ORDER BY worker_id ASC
            """
        )
        return [
            WorkerNodeInfo(
                worker_id=r[0],
                capacity=r[1],
                active_tasks=json.loads(r[2]),
                last_heartbeat=r[3],
                status=r[4],
                host=r[5],
                port=r[6],
            )
            for r in cursor.fetchall()
        ]

    def get_assigned_tasks(self, worker_id: str) -> list[str]:
        """Fetch all tasks assigned to a specific worker."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            SELECT task_id FROM stealing_tasks
            WHERE assigned_worker_id = ? ORDER BY updated_at ASC
            """,
            (worker_id,),
        )
        return [r[0] for r in cursor.fetchall()]
