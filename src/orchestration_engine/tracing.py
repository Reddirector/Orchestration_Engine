"""
Structured Tracing and Observability Exporters for Orchestration Engine.

Generates Chrome Tracing (perfetto/speedscope compatible) and OpenTelemetry W3C
span collections from SQLite run events. Zero external runtime dependencies.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    """A single traced execution span (workflow or task)."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "OK"
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def to_chrome_event(self, pid: int = 1, tid: int = 1) -> dict[str, Any]:
        """Convert span to Chrome Trace Event format (microseconds)."""
        ts_micros = int(self.start_time * 1_000_000)
        dur_micros = int(self.duration_seconds * 1_000_000)
        return {
            "name": self.name,
            "cat": "orchestration",
            "ph": "X",  # Complete event
            "ts": ts_micros,
            "dur": max(1, dur_micros),
            "pid": pid,
            "tid": tid,
            "args": {
                "span_id": self.span_id,
                "status": self.status,
                **self.attributes,
            },
        }

    def to_otel_dict(self) -> dict[str, Any]:
        """Convert span to OpenTelemetry-compatible dictionary."""
        start_nano = int(self.start_time * 1_000_000_000)
        end_nano = int(self.end_time * 1_000_000_000)
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id or "",
            "name": self.name,
            "kind": "SPAN_KIND_INTERNAL",
            "startTimeUnixNano": start_nano,
            "endTimeUnixNano": end_nano,
            "status": {"code": 1 if self.status == "OK" else 2},
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in self.attributes.items()
            ],
        }


def extract_run_spans(conn: sqlite3.Connection, run_id: str) -> list[Span]:
    """
    Reconstruct spans for a workflow run and all its tasks from SQLite event logs.
    """
    cursor = conn.cursor()

    # 1. Fetch workflow run row
    cursor.execute(
        """
        SELECT workflow_id, started_at, finished_at, status, definition_json
        FROM runs WHERE run_id = ?
        """,
        (run_id,),
    )
    run_row = cursor.fetchone()
    if not run_row:
        return []

    wf_id, started_at, finished_at, run_status, def_json = run_row
    end_time = finished_at if finished_at is not None else (started_at or 0.0)
    root_span_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{run_id}-root").hex[:16]

    root_span = Span(
        name=f"workflow:{wf_id}",
        trace_id=run_id,
        span_id=root_span_id,
        start_time=started_at or 0.0,
        end_time=end_time,
        status="OK" if run_status == "succeeded" else "ERROR",
        attributes={"workflow_id": wf_id, "status": run_status, "run_id": run_id},
    )

    spans = [root_span]

    # 2. Fetch task timing and attempts from task_events
    cursor.execute(
        """
        SELECT task_id, MIN(timestamp), MAX(timestamp), MAX(attempt_count), new_state, error
        FROM task_events
        WHERE run_id = ?
        GROUP BY task_id
        """,
        (run_id,),
    )
    for t_id, t_min, t_max, attempts, final_state, err in cursor.fetchall():
        t_span_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{run_id}-{t_id}").hex[:16]
        spans.append(
            Span(
                name=f"task:{t_id}",
                trace_id=run_id,
                span_id=t_span_id,
                parent_span_id=root_span_id,
                start_time=t_min or started_at or 0.0,
                end_time=t_max or end_time,
                status="OK" if final_state == "succeeded" else "ERROR",
                attributes={
                    "task_id": t_id,
                    "attempts": attempts or 1,
                    "state": final_state,
                    "error": err or "",
                },
            )
        )

    return spans


class TraceExporter:
    """Zero-dependency trace exporter for Chrome and OpenTelemetry formats."""

    @staticmethod
    def to_chrome_trace(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        """Generate Chrome Trace Event format (for chrome://tracing and Perfetto)."""
        spans = extract_run_spans(conn, run_id)
        events = [s.to_chrome_event() for s in spans]
        return {
            "traceEvents": events,
            "displayTimeUnit": "ms",
            "metadata": {"run_id": run_id, "spans_count": len(spans)},
        }

    @staticmethod
    def to_otel_trace(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        """Generate OpenTelemetry W3C trace payload."""
        spans = extract_run_spans(conn, run_id)
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "orchestration-engine"},
                            },
                            {"key": "run.id", "value": {"stringValue": run_id}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "orchestration_engine.tracer", "version": "0.9.0"},
                            "spans": [s.to_otel_dict() for s in spans],
                        }
                    ],
                }
            ]
        }
