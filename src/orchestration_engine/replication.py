"""Multi-Node SQLite Replication and Change Data Capture (CDC) Synchronization.

Enables primary-to-replica event stream synchronization across distributed worker nodes
using standard library HTTP and incremental change capture on runs, task_events, and task_outputs.
"""

from __future__ import annotations

import dataclasses
import http.server
import json
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from orchestration_engine.persistence import get_connection


@dataclasses.dataclass(frozen=True)
class CDCRun:
    """Captured workflow run summary."""

    run_id: str
    workflow_id: str
    started_at: float
    finished_at: float | None
    status: str
    definition_json: str = "{}"


@dataclasses.dataclass(frozen=True)
class CDCEvent:
    """Captured task transition event."""

    event_id: int
    workflow_id: str
    task_id: str
    old_state: str
    new_state: str
    timestamp: float
    attempt_count: int
    run_id: str


@dataclasses.dataclass(frozen=True)
class CDCOutput:
    """Captured task output or error payload."""

    run_id: str
    task_id: str
    output_json: str | None
    error: str | None


@dataclasses.dataclass(frozen=True)
class CDCBatch:
    """Batch of change data capture entries up to last_event_id."""

    last_event_id: int
    runs: list[CDCRun]
    events: list[CDCEvent]
    outputs: list[CDCOutput]

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_event_id": self.last_event_id,
            "runs": [dataclasses.asdict(r) for r in self.runs],
            "events": [dataclasses.asdict(e) for e in self.events],
            "outputs": [dataclasses.asdict(o) for o in self.outputs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CDCBatch:
        return cls(
            last_event_id=int(data["last_event_id"]),
            runs=[CDCRun(**r) for r in data.get("runs", [])],
            events=[CDCEvent(**e) for e in data.get("events", [])],
            outputs=[CDCOutput(**o) for o in data.get("outputs", [])],
        )


class CDCReplicationSource:
    """Reads incremental mutations from a primary SQLite database."""

    def __init__(self, conn_or_path: sqlite3.Connection | str) -> None:
        if isinstance(conn_or_path, str):
            self.db_path: str | None = conn_or_path
            self._conn: sqlite3.Connection | None = None
        else:
            self.db_path = None
            self._conn = conn_or_path

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path is not None:
            return get_connection(self.db_path)
        assert self._conn is not None
        return self._conn

    def read_changes(self, since_event_id: int = 0, limit: int = 100) -> CDCBatch:
        """Fetch runs, transition events, and matching task outputs since since_event_id."""
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                """
                SELECT id, workflow_id, task_id, old_state, new_state, timestamp,
                       attempt_count, run_id
                FROM task_events
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (since_event_id, limit),
            )
            rows = cursor.fetchall()

        events: list[CDCEvent] = []
        max_id = since_event_id
        run_ids: set[str] = set()
        run_task_pairs: set[tuple[str, str]] = set()

        for r in rows:
            ev = CDCEvent(
                event_id=r[0],
                workflow_id=r[1],
                task_id=r[2],
                old_state=r[3],
                new_state=r[4],
                timestamp=r[5],
                attempt_count=r[6] or 0,
                run_id=r[7] or "",
            )
            events.append(ev)
            if ev.event_id > max_id:
                max_id = ev.event_id
            if ev.run_id:
                run_ids.add(ev.run_id)
            if ev.run_id and ev.task_id:
                run_task_pairs.add((ev.run_id, ev.task_id))

        # Query runs
        runs: list[CDCRun] = []
        with conn:
            for rid in run_ids:
                r_cursor = conn.execute(
                    "SELECT run_id, workflow_id, started_at, finished_at, status, definition_json "
                    "FROM runs WHERE run_id = ?",
                    (rid,),
                )
                r_row = r_cursor.fetchone()
                if r_row:
                    runs.append(
                        CDCRun(
                            run_id=r_row[0],
                            workflow_id=r_row[1],
                            started_at=r_row[2],
                            finished_at=r_row[3],
                            status=r_row[4],
                            definition_json=r_row[5] or "{}",
                        )
                    )

        # Query matching outputs
        outputs: list[CDCOutput] = []
        if run_task_pairs:
            with conn:
                for rid, tid in run_task_pairs:
                    out_cursor = conn.execute(
                        "SELECT run_id, task_id, output_json, error FROM task_outputs "
                        "WHERE run_id = ? AND task_id = ?",
                        (rid, tid),
                    )
                    out_row = out_cursor.fetchone()
                    if out_row:
                        outputs.append(
                            CDCOutput(
                                run_id=out_row[0],
                                task_id=out_row[1],
                                output_json=out_row[2],
                                error=out_row[3],
                            )
                        )

        return CDCBatch(last_event_id=max_id, runs=runs, events=events, outputs=outputs)


class CDCReplicationTarget:
    """Applies change data capture batches onto a replica SQLite database."""

    def __init__(self, conn_or_path: sqlite3.Connection | str) -> None:
        if isinstance(conn_or_path, str):
            self.db_path: str | None = conn_or_path
            self._conn: sqlite3.Connection | None = None
        else:
            self.db_path = None
            self._conn = conn_or_path
        self._init_target_cursor_table()

    def _get_conn(self) -> sqlite3.Connection:
        if self.db_path is not None:
            return get_connection(self.db_path)
        assert self._conn is not None
        return self._conn

    def _init_target_cursor_table(self) -> None:
        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replication_cursor (
                    source_id TEXT PRIMARY KEY,
                    last_synced_event_id INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def get_last_synced_event_id(self, source_id: str = "default") -> int:
        """Return the highest synced event ID."""
        conn = self._get_conn()
        with conn:
            cursor = conn.execute(
                "SELECT last_synced_event_id FROM replication_cursor WHERE source_id = ?",
                (source_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def apply_batch(self, batch: CDCBatch, source_id: str = "default") -> int:
        """Idempotently apply incoming runs, events, and outputs to replica."""
        if not batch.events and not batch.outputs and not batch.runs:
            return 0

        conn = self._get_conn()
        with conn:
            # 1. Insert runs first to satisfy foreign keys in task_outputs
            for r in batch.runs:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO runs (
                        run_id, workflow_id, started_at, finished_at, status, definition_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r.run_id,
                        r.workflow_id,
                        r.started_at,
                        r.finished_at,
                        r.status,
                        r.definition_json,
                    ),
                )

            # 2. Insert task events
            for ev in batch.events:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO task_events (
                        id, workflow_id, task_id, old_state, new_state, timestamp,
                        attempt_count, run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev.event_id,
                        ev.workflow_id,
                        ev.task_id,
                        ev.old_state,
                        ev.new_state,
                        ev.timestamp,
                        ev.attempt_count,
                        ev.run_id,
                    ),
                )

            # 3. Insert task outputs
            for out in batch.outputs:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_outputs (
                        run_id, task_id, output_json, error
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (out.run_id, out.task_id, out.output_json, out.error),
                )

            conn.execute(
                """
                INSERT OR REPLACE INTO replication_cursor (
                    source_id, last_synced_event_id, updated_at
                ) VALUES (?, ?, ?)
                """,
                (source_id, batch.last_event_id, time.time()),
            )

        return len(batch.events)


class ReplicationHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler serving CDC change batches."""

    source: CDCReplicationSource

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/cdc":
            params = urllib.parse.parse_qs(parsed.query)
            since = int(params.get("since", ["0"])[0])
            limit = int(params.get("limit", ["100"])[0])
            batch = self.source.read_changes(since_event_id=since, limit=limit)
            body = json.dumps(batch.to_dict()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


class ReplicationServer:
    """Non-blocking primary replication HTTP server."""

    def __init__(
        self,
        db_path: str,
        host: str = "127.0.0.1",
        port: int = 9200,
    ) -> None:
        self.db_path = db_path
        self.host = host
        self.port = port
        self.source = CDCReplicationSource(db_path)
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler_cls = type(
            "BoundReplicationHandler",
            (ReplicationHandler,),
            {"source": self.source},
        )
        self._server = http.server.HTTPServer((self.host, self.port), handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=1.0)


class ReplicationClient:
    """Client polling primary replication server and syncing to replica database."""

    def __init__(
        self,
        replica_conn_or_path: sqlite3.Connection | str,
        primary_url: str = "http://127.0.0.1:9200",
        source_id: str = "default",
    ) -> None:
        self.target = CDCReplicationTarget(replica_conn_or_path)
        self.primary_url = primary_url.rstrip("/")
        self.source_id = source_id

    def sync_once(self, limit: int = 100) -> int:
        """Poll latest changes from primary and apply to replica."""
        since = self.target.get_last_synced_event_id(self.source_id)
        url = f"{self.primary_url}/cdc?since={since}&limit={limit}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        batch = CDCBatch.from_dict(data)
        return self.target.apply_batch(batch, self.source_id)
