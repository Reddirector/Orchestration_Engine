"""
Human-in-the-Loop and External Signals for Orchestration Engine.

Allows workflow tasks to pause execution awaiting an external signal, human approval,
or webhook notification. Thread-safe, async-compatible, with persistent SQLite audit storage.
Zero external runtime dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from typing import Any

logger = logging.getLogger("orchestration_engine.signals")


class SignalTimeoutError(TimeoutError):
    """Raised when waiting for a signal exceeds the timeout period."""


class SignalBroker:
    """
    Coordinator for human-in-the-loop approvals and external event signals.
    """

    def __init__(self, db_path: str = "orchestration.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._signals: dict[tuple[str, str], list[Any]] = {}
        self._events: dict[tuple[str, str], threading.Event] = {}
        self._async_events: dict[tuple[str, str], asyncio.Event] = {}

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                payload_json TEXT,
                timestamp REAL NOT NULL,
                consumed INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_signals_run_name
            ON workflow_signals(run_id, signal_name)
            """
        )
        conn.commit()

    def send_signal(
        self,
        run_id: str,
        signal_name: str,
        payload: Any = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """
        Send a signal with payload to a running or paused workflow.

        Persists to SQLite and unblocks any waiting threads or coroutines.
        """
        now = time.time()
        payload_str = json.dumps(payload) if payload is not None else None

        # Persist to database
        should_close = False
        if conn is None:
            from orchestration_engine.persistence import get_connection

            conn = get_connection(self.db_path)
            should_close = True

        try:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO workflow_signals
                (run_id, signal_name, payload_json, timestamp, consumed)
                VALUES (?, ?, ?, ?, 0)
                """,
                (run_id, signal_name, payload_str, now),
            )
            conn.commit()
        finally:
            if should_close:
                conn.close()

        # Notify in-memory listeners
        key = (run_id, signal_name)
        with self._lock:
            if key not in self._signals:
                self._signals[key] = []
            self._signals[key].append(payload)

            if key in self._events:
                self._events[key].set()

            if key in self._async_events:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(self._async_events[key].set)
                else:
                    self._async_events[key].set()

        logger.info("Signal '%s' sent to run '%s'", signal_name, run_id)

    def wait_for_signal(
        self,
        run_id: str,
        signal_name: str,
        timeout: float | None = 60.0,
        conn: sqlite3.Connection | None = None,
    ) -> Any:
        """
        Synchronously block until signal is received or timeout expires.
        """
        key = (run_id, signal_name)

        # Check existing signal in memory
        with self._lock:
            if key in self._signals and self._signals[key]:
                return self._signals[key].pop(0)
            if key not in self._events:
                self._events[key] = threading.Event()
            ev = self._events[key]

        # Check existing signal in DB if not found in memory
        should_close = False
        if conn is None:
            from orchestration_engine.persistence import get_connection

            conn = get_connection(self.db_path)
            should_close = True

        try:
            self._ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, payload_json FROM workflow_signals
                WHERE run_id = ? AND signal_name = ? AND consumed = 0
                ORDER BY timestamp ASC LIMIT 1
                """,
                (run_id, signal_name),
            )
            row = cursor.fetchone()
            if row:
                sig_id, p_raw = row
                conn.execute(
                    "UPDATE workflow_signals SET consumed = 1 WHERE id = ?",
                    (sig_id,),
                )
                conn.commit()
                return json.loads(p_raw) if p_raw is not None else None
        finally:
            if should_close:
                conn.close()

        # Wait on event
        signaled = ev.wait(timeout=timeout)
        if not signaled:
            raise SignalTimeoutError(
                f"Timed out after {timeout}s waiting for signal '{signal_name}' on run '{run_id}'"
            )

        with self._lock:
            ev.clear()
            if key in self._signals and self._signals[key]:
                return self._signals[key].pop(0)
            return None

    async def wait_for_signal_async(
        self,
        run_id: str,
        signal_name: str,
        timeout: float | None = 60.0,
    ) -> Any:
        """
        Asynchronously await signal arrival without blocking the event loop.
        """
        key = (run_id, signal_name)
        with self._lock:
            if key in self._signals and self._signals[key]:
                return self._signals[key].pop(0)
            if key not in self._async_events:
                self._async_events[key] = asyncio.Event()
            ev = self._async_events[key]

        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except TimeoutError as err:
            raise SignalTimeoutError(
                f"Timed out after {timeout}s waiting for signal '{signal_name}' on run '{run_id}'"
            ) from err

        with self._lock:
            ev.clear()
            if key in self._signals and self._signals[key]:
                return self._signals[key].pop(0)
            return None

    def list_signals(
        self, run_id: str, conn: sqlite3.Connection | None = None
    ) -> list[dict[str, Any]]:
        """Return history of all signals delivered to a run."""
        should_close = False
        if conn is None:
            from orchestration_engine.persistence import get_connection

            conn = get_connection(self.db_path)
            should_close = True

        try:
            self._ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, signal_name, payload_json, timestamp, consumed
                FROM workflow_signals
                WHERE run_id = ?
                ORDER BY timestamp ASC
                """,
                (run_id,),
            )
            signals = []
            for row in cursor.fetchall():
                p_val = None
                if row[2] is not None:
                    try:
                        p_val = json.loads(row[2])
                    except Exception:
                        p_val = row[2]
                signals.append(
                    {
                        "id": row[0],
                        "signal_name": row[1],
                        "payload": p_val,
                        "timestamp": row[3],
                        "consumed": bool(row[4]),
                    }
                )
            return signals
        finally:
            if should_close:
                conn.close()


# Default singleton instance
default_signal_broker = SignalBroker()
