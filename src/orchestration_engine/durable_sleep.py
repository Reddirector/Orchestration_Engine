"""Durable Timers and Long-Running Workflow Suspensions.

Allows tasks and workflows to register durable delays and wake-up times backed by SQLite.
Workflows can suspend without holding open OS threads or worker processes, surviving
process restarts and host reboots.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from orchestration_engine.errors import PersistenceError
from orchestration_engine.persistence import get_connection

DURABLE_SLEEP_KEY = "__durable_sleep__"


class TimerStatus(StrEnum):
    """Lifecycle status of a durable timer."""

    ACTIVE = "active"
    FIRED = "fired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DurableTimer:
    """Representation of an SQLite-backed durable timer."""

    timer_id: str
    run_id: str
    task_id: str
    fire_at: float
    created_at: float
    status: TimerStatus
    payload: dict[str, Any]

    @property
    def is_due(self) -> bool:
        """Check if current time has passed the scheduled wake-up time."""
        return time.time() >= self.fire_at and self.status == TimerStatus.ACTIVE


def create_sleep_marker(
    delay_seconds: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper for task runners to signal a durable sleep requirement to coordinators."""
    return {
        DURABLE_SLEEP_KEY: True,
        "delay_seconds": max(0.0, float(delay_seconds)),
        "payload": payload or {},
    }


class TimerStore:
    """Persistent SQLite store for scheduling and polling durable timers."""

    def __init__(
        self,
        db_path: str = "orchestration.db",
        conn: sqlite3.Connection | None = None,
    ) -> None:
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
                    CREATE TABLE IF NOT EXISTS durable_timers (
                        timer_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        fire_at REAL NOT NULL,
                        created_at REAL NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dt_status_fire "
                    "ON durable_timers(status, fire_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_dt_run_id ON durable_timers(run_id)"
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to initialize durable_timers schema: {exc}") from exc
        finally:
            if self._conn is None:
                conn.close()

    def create_timer(
        self,
        *,
        run_id: str,
        task_id: str,
        delay_seconds: float,
        payload: dict[str, Any] | None = None,
        timer_id: str | None = None,
    ) -> DurableTimer:
        """Create and persist a new durable timer."""
        tid = timer_id or uuid.uuid4().hex
        now = time.time()
        fire_at = now + max(0.0, float(delay_seconds))
        status = TimerStatus.ACTIVE
        payload_dict = payload or {}
        payload_str = json.dumps(payload_dict)

        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO durable_timers (
                        timer_id, run_id, task_id, fire_at, created_at, status, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (tid, run_id, task_id, fire_at, now, status.value, payload_str),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to create durable timer '{tid}': {exc}") from exc
        finally:
            if self._conn is None:
                conn.close()

        return DurableTimer(
            timer_id=tid,
            run_id=run_id,
            task_id=task_id,
            fire_at=fire_at,
            created_at=now,
            status=status,
            payload=payload_dict,
        )

    def get_timer(self, timer_id: str) -> DurableTimer | None:
        """Retrieve a specific timer by its ID."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT timer_id, run_id, task_id, fire_at, created_at, status, payload_json
                FROM durable_timers WHERE timer_id = ?
                """,
                (timer_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return DurableTimer(
                timer_id=row[0],
                run_id=row[1],
                task_id=row[2],
                fire_at=float(row[3]),
                created_at=float(row[4]),
                status=TimerStatus(row[5]),
                payload=json.loads(row[6]),
            )
        finally:
            if self._conn is None:
                conn.close()

    def get_due_timers(self, now: float | None = None) -> list[DurableTimer]:
        """Fetch all ACTIVE timers whose scheduled fire_at is <= now."""
        current_time = time.time() if now is None else now
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT timer_id, run_id, task_id, fire_at, created_at, status, payload_json
                FROM durable_timers
                WHERE status = ? AND fire_at <= ?
                ORDER BY fire_at ASC
                """,
                (TimerStatus.ACTIVE.value, current_time),
            )
            timers = []
            for row in cursor.fetchall():
                timers.append(
                    DurableTimer(
                        timer_id=row[0],
                        run_id=row[1],
                        task_id=row[2],
                        fire_at=float(row[3]),
                        created_at=float(row[4]),
                        status=TimerStatus(row[5]),
                        payload=json.loads(row[6]),
                    )
                )
            return timers
        finally:
            if self._conn is None:
                conn.close()

    def mark_timer_fired(self, timer_id: str) -> bool:
        """Mark an active timer as FIRED."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE durable_timers SET status = ?
                    WHERE timer_id = ? AND status = ?
                    """,
                    (TimerStatus.FIRED.value, timer_id, TimerStatus.ACTIVE.value),
                )
                return cursor.rowcount > 0
        finally:
            if self._conn is None:
                conn.close()

    def cancel_timer(self, timer_id: str) -> bool:
        """Cancel an active timer."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE durable_timers SET status = ?
                    WHERE timer_id = ? AND status = ?
                    """,
                    (TimerStatus.CANCELLED.value, timer_id, TimerStatus.ACTIVE.value),
                )
                return cursor.rowcount > 0
        finally:
            if self._conn is None:
                conn.close()

    def cancel_timers_for_run(self, run_id: str) -> int:
        """Cancel all pending active timers for a specific workflow run."""
        conn = self._get_conn()
        try:
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE durable_timers SET status = ?
                    WHERE run_id = ? AND status = ?
                    """,
                    (TimerStatus.CANCELLED.value, run_id, TimerStatus.ACTIVE.value),
                )
                return cursor.rowcount
        finally:
            if self._conn is None:
                conn.close()
