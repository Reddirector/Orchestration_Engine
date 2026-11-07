"""
Self-Healing Workflow Watchdog & Auto-Supervisor for Orchestration Engine.

Monitors active SQLite workflow runs for stuck tasks or zombie states,
automatically applies remediation policies (RETRY, ABORT_RUN, NOTIFY),
and records diagnostic incident trails.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

from orchestration_engine.persistence import get_connection


class AutoRemedy(StrEnum):
    """Action taken by the supervisor when a zombie task is identified."""

    RETRY = "RETRY"
    ABORT_RUN = "ABORT_RUN"
    NOTIFY = "NOTIFY"


@dataclass
class ZombieTaskIncident:
    """Represents a diagnostic incident recorded by the supervisor."""

    incident_id: str
    run_id: str
    task_id: str
    elapsed_seconds: float
    remedy_applied: AutoRemedy
    reason: str
    created_at: float


@dataclass
class SupervisorPolicy:
    """Configuration governing watchdog timeouts and auto-healing remedies."""

    stuck_timeout_seconds: float = 300.0
    default_remedy: AutoRemedy = AutoRemedy.RETRY
    max_auto_retries: int = 3


class WorkflowSupervisor:
    """Watchdog daemon scanning SQLite runs for deadlocked or abandoned tasks."""

    def __init__(
        self,
        conn_or_path: sqlite3.Connection | str | None = None,
        policy: SupervisorPolicy | None = None,
    ) -> None:
        if conn_or_path is None or conn_or_path == ":memory:":
            self._db_path: str | None = None
            self._conn: sqlite3.Connection | None = get_connection(":memory:")
        elif isinstance(conn_or_path, str):
            self._db_path = conn_or_path
            self._conn = None
        else:
            self._db_path = None
            self._conn = conn_or_path

        self.policy = policy or SupervisorPolicy()
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self._db_path is not None:
            return get_connection(self._db_path)
        raise RuntimeError("WorkflowSupervisor has no database connection configured.")

    def _init_tables(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_incidents (
                    incident_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    remedy_applied TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_supervisor_run
                ON supervisor_incidents (run_id)
                """
            )

    def scan_and_heal(
        self,
        time_source: float | None = None,
    ) -> list[ZombieTaskIncident]:
        """Scan active runs for tasks stuck in RUNNING state past the configured timeout."""
        now = time.time() if time_source is None else time_source
        conn = self._get_conn()

        incidents: list[ZombieTaskIncident] = []

        with conn:
            # Find active runs and their workflow_id
            cursor = conn.execute(
                "SELECT run_id, workflow_id FROM runs WHERE status = 'running'"
            )
            active_runs = cursor.fetchall()

            for run_id, wf_id in active_runs:
                # Find latest event per task in this run
                cursor = conn.execute(
                    """
                    SELECT task_id, new_state, timestamp, attempt_count
                    FROM task_events
                    WHERE run_id = ?
                    AND id IN (
                        SELECT MAX(id)
                        FROM task_events
                        WHERE run_id = ?
                        GROUP BY task_id
                    )
                    """,
                    (run_id, run_id),
                )
                task_latest = cursor.fetchall()

                for tid, state, ts, attempt in task_latest:
                    if state.lower() == "running":
                        elapsed = now - ts
                        if elapsed >= self.policy.stuck_timeout_seconds:
                            # Zombie task identified!
                            inc = self._heal_task(
                                conn, run_id, wf_id, tid, elapsed, attempt, now
                            )
                            incidents.append(inc)

        return incidents

    def _heal_task(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        workflow_id: str,
        task_id: str,
        elapsed: float,
        attempt: int,
        now: float,
    ) -> ZombieTaskIncident:
        """Apply the configured remedy to a stuck task."""
        # Check prior incidents count for this task
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM supervisor_incidents
            WHERE run_id = ? AND task_id = ? AND remedy_applied = 'RETRY'
            """,
            (run_id, task_id),
        )
        prior_retries = cursor.fetchone()[0]

        remedy = self.policy.default_remedy
        reason = (
            f"Task stuck in RUNNING for {elapsed:.1f}s "
            f"(threshold: {self.policy.stuck_timeout_seconds:.1f}s)"
        )

        if remedy == AutoRemedy.RETRY:
            if prior_retries >= self.policy.max_auto_retries:
                # Exceeded allowed supervisor retries -> abort run
                remedy = AutoRemedy.ABORT_RUN
                reason += f"; exceeded max auto-retries ({self.policy.max_auto_retries})"

        if remedy == AutoRemedy.RETRY:
            # Emit ready event to allow retry
            conn.execute(
                """
                INSERT INTO task_events (
                    run_id, workflow_id, task_id,
                    old_state, new_state, timestamp, attempt_count, error
                ) VALUES (?, ?, ?, 'running', 'ready', ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    task_id,
                    now,
                    attempt,
                    "Supervisor auto-remedy: reset to ready",
                ),
            )
        elif remedy == AutoRemedy.ABORT_RUN:
            # Mark task failed and run failed
            conn.execute(
                """
                INSERT INTO task_events (
                    run_id, workflow_id, task_id,
                    old_state, new_state, timestamp, attempt_count, error
                ) VALUES (?, ?, ?, 'running', 'failed', ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    task_id,
                    now,
                    attempt,
                    f"Supervisor aborted: {reason}",
                ),
            )
            conn.execute(
                "UPDATE runs SET status = 'failed', finished_at = ? WHERE run_id = ?",
                (now, run_id),
            )

        inc_id = f"inc_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO supervisor_incidents (
                incident_id, run_id, task_id, elapsed_seconds, remedy_applied, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (inc_id, run_id, task_id, elapsed, remedy.value, reason, now),
        )

        return ZombieTaskIncident(
            incident_id=inc_id,
            run_id=run_id,
            task_id=task_id,
            elapsed_seconds=elapsed,
            remedy_applied=remedy,
            reason=reason,
            created_at=now,
        )

    def get_incidents(self, run_id: str | None = None) -> list[ZombieTaskIncident]:
        """Fetch recorded diagnostic supervisor incidents."""
        conn = self._get_conn()
        cols = (
            "incident_id, run_id, task_id, elapsed_seconds, "
            "remedy_applied, reason, created_at"
        )
        if run_id:
            cursor = conn.execute(
                f"SELECT {cols} FROM supervisor_incidents "
                "WHERE run_id = ? ORDER BY created_at DESC",
                (run_id,),
            )
        else:
            cursor = conn.execute(
                f"SELECT {cols} FROM supervisor_incidents ORDER BY created_at DESC"
            )

        return [
            ZombieTaskIncident(
                incident_id=r[0],
                run_id=r[1],
                task_id=r[2],
                elapsed_seconds=r[3],
                remedy_applied=AutoRemedy(r[4]),
                reason=r[5],
                created_at=r[6],
            )
            for r in cursor.fetchall()
        ]
