"""Stateful Incremental ETL and Pipeline Watermark Store.

Enables data pipelines, CDC (Change Data Capture) feeds, and incremental batch
workflows to track high-watermarks (e.g. last_synced_timestamp, last_row_id,
Kafka offsets) atomically in SQLite WAL mode.
"""

from __future__ import annotations

import dataclasses
import json
import time
from typing import Any

from orchestration_engine.persistence import get_connection


@dataclasses.dataclass(frozen=True)
class Watermark:
    """State of an incremental watermark."""

    pipeline_id: str
    key: str
    value: Any
    updated_at: float
    run_id: str | None = None


class WatermarkStore:
    """Persistent watermark coordinator backed by SQLite."""

    def __init__(self, db_path: str = "orchestration.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_watermarks (
                    pipeline_id TEXT NOT NULL,
                    watermark_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    run_id TEXT,
                    PRIMARY KEY (pipeline_id, watermark_key)
                )
                """
            )

    def get_watermark(
        self,
        pipeline_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        """Retrieve the current watermark value for a pipeline key."""
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(
                "SELECT value_json FROM pipeline_watermarks "
                "WHERE pipeline_id = ? AND watermark_key = ?",
                (pipeline_id, key),
            )
            row = cursor.fetchone()
            if not row:
                return default
            return json.loads(row[0])

    def set_watermark(
        self,
        pipeline_id: str,
        key: str,
        value: Any,
        *,
        run_id: str | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Atomically update the watermark value."""
        now = timestamp if timestamp is not None else time.time()
        val_json = json.dumps(value)
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO pipeline_watermarks (
                    pipeline_id, watermark_key, value_json, updated_at, run_id
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(pipeline_id, watermark_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at,
                    run_id = excluded.run_id
                """,
                (pipeline_id, key, val_json, now, run_id),
            )

    def advance_watermark(
        self,
        pipeline_id: str,
        key: str,
        new_value: Any,
        *,
        run_id: str | None = None,
    ) -> None:
        """Alias for set_watermark representing forward progression."""
        self.set_watermark(pipeline_id, key, new_value, run_id=run_id)

    def list_watermarks(self, pipeline_id: str | None = None) -> list[Watermark]:
        """List all tracked watermarks, optionally filtered by pipeline."""
        query = (
            "SELECT pipeline_id, watermark_key, value_json, updated_at, run_id "
            "FROM pipeline_watermarks"
        )
        params: list[Any] = []
        if pipeline_id:
            query += " WHERE pipeline_id = ?"
            params.append(pipeline_id)

        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [
            Watermark(
                pipeline_id=r[0],
                key=r[1],
                value=json.loads(r[2]),
                updated_at=r[3],
                run_id=r[4],
            )
            for r in rows
        ]
