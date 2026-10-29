"""Persistent Dead Letter Queue (DLQ) for unrecoverable task failures.

Captures failed task payloads, parameters, error messages, and stack traces
into an audit table for post-mortem diagnostics, triage, and replayability.
"""

from __future__ import annotations

import dataclasses
import json
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import Hooks, Task
from orchestration_engine.persistence import get_connection


@dataclasses.dataclass(frozen=True)
class DeadLetterMessage:
    """A captured task failure in the Dead Letter Queue."""

    message_id: str
    workflow_id: str
    run_id: str
    task_id: str
    inputs: dict[str, Any]
    error_message: str
    stack_trace: str
    timestamp: float
    attempt_count: int
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


class DeadLetterQueue:
    """SQLite-backed persistent Dead Letter Queue."""

    def __init__(self, db_path: str = "orchestration.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letter_queue (
                    message_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    stack_trace TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dlq_wf ON dead_letter_queue(workflow_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dlq_run ON dead_letter_queue(run_id)"
            )

    def enqueue(
        self,
        *,
        workflow_id: str,
        run_id: str,
        task_id: str,
        inputs: dict[str, Any] | None = None,
        error: str | Exception,
        stack_trace: str | None = None,
        attempt_count: int = 1,
        metadata: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> str:
        """Enqueue a failed task execution into the DLQ."""
        msg_id = uuid.uuid4().hex
        err_msg = str(error)
        st = stack_trace or traceback.format_exc()
        ts = timestamp if timestamp is not None else time.time()
        inp_json = json.dumps(inputs or {})
        meta_json = json.dumps(metadata or {})

        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO dead_letter_queue (
                    message_id, workflow_id, run_id, task_id,
                    inputs_json, error_message, stack_trace,
                    timestamp, attempt_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    workflow_id,
                    run_id,
                    task_id,
                    inp_json,
                    err_msg,
                    st,
                    ts,
                    attempt_count,
                    meta_json,
                ),
            )
        return msg_id

    def list_messages(
        self,
        *,
        workflow_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[DeadLetterMessage]:
        """List dead letter messages with optional filters."""
        query = (
            "SELECT message_id, workflow_id, run_id, task_id, inputs_json, "
            "error_message, stack_trace, timestamp, attempt_count, metadata_json "
            "FROM dead_letter_queue WHERE 1=1"
        )
        params: list[Any] = []
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        messages = []
        for r in rows:
            messages.append(
                DeadLetterMessage(
                    message_id=r[0],
                    workflow_id=r[1],
                    run_id=r[2],
                    task_id=r[3],
                    inputs=json.loads(r[4]),
                    error_message=r[5],
                    stack_trace=r[6],
                    timestamp=r[7],
                    attempt_count=r[8],
                    metadata=json.loads(r[9]),
                )
            )
        return messages

    def get_message(self, message_id: str) -> DeadLetterMessage | None:
        """Fetch a specific DLQ message by ID."""
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(
                "SELECT message_id, workflow_id, run_id, task_id, inputs_json, "
                "error_message, stack_trace, timestamp, attempt_count, metadata_json "
                "FROM dead_letter_queue WHERE message_id = ?",
                (message_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return DeadLetterMessage(
                message_id=r[0],
                workflow_id=r[1],
                run_id=r[2],
                task_id=r[3],
                inputs=json.loads(r[4]),
                error_message=r[5],
                stack_trace=r[6],
                timestamp=r[7],
                attempt_count=r[8],
                metadata=json.loads(r[9]),
            )

    def replay(self, message_id: str, runner_func: Callable[..., Any]) -> Any:
        """Replay a dead letter task execution using its recorded inputs.

        If execution succeeds, the message is automatically removed from the DLQ.
        """
        msg = self.get_message(message_id)
        if msg is None:
            raise KeyError(f"Dead letter message '{message_id}' not found")

        # Attempt re-execution
        try:
            res = runner_func(**msg.inputs)
        except TypeError:
            res = runner_func(msg.inputs)

        # On success, purge from DLQ
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                "DELETE FROM dead_letter_queue WHERE message_id = ?",
                (message_id,),
            )
        return res

    def purge(
        self,
        *,
        workflow_id: str | None = None,
        older_than_seconds: float | None = None,
    ) -> int:
        """Purge dead letter messages matching criteria."""
        query = "DELETE FROM dead_letter_queue WHERE 1=1"
        params: list[Any] = []
        if workflow_id:
            query += " AND workflow_id = ?"
            params.append(workflow_id)
        if older_than_seconds is not None:
            cutoff = time.time() - older_than_seconds
            query += " AND timestamp < ?"
            params.append(cutoff)

        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(query, params)
            return cursor.rowcount


def create_dlq_hook(
    dlq: DeadLetterQueue,
    *,
    workflow_id: str,
    run_id: str,
) -> Hooks:
    """Create engine Hooks that automatically route fatal task failures to the DLQ."""

    def on_task_failed(task: Task) -> None:
        dlq.enqueue(
            workflow_id=workflow_id,
            run_id=run_id,
            task_id=task.task_id,
            inputs=getattr(task, "inputs", {}),
            error=task.last_error or "Task failed",
            attempt_count=getattr(task, "attempt_count", 1),
        )

    return Hooks(on_task_failed=on_task_failed)
