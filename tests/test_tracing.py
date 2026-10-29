"""Unit tests for TracingExporter and OpenTelemetry / Chrome traces."""

from __future__ import annotations

import sqlite3
import time

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.runner import run_workflow
from orchestration_engine.tracing import Span, TraceExporter, extract_run_spans


def test_span_conversion() -> None:
    span = Span(
        name="test_span",
        trace_id="trace-123",
        span_id="span-456",
        start_time=100.0,
        end_time=101.5,
        status="OK",
        attributes={"key": "val"},
    )
    assert span.duration_seconds == 1.5

    chrome_ev = span.to_chrome_event()
    assert chrome_ev["ph"] == "X"
    assert chrome_ev["ts"] == 100_000_000
    assert chrome_ev["dur"] == 1_500_000
    assert chrome_ev["args"]["key"] == "val"

    otel_ev = span.to_otel_dict()
    assert otel_ev["traceId"] == "trace-123"
    assert otel_ev["name"] == "test_span"


def test_trace_exporter_e2e(conn: sqlite3.Connection) -> None:
    wf = (
        WorkflowBuilder("traced-wf")
        .task("step1", name="Step 1")
        .task("step2", name="Step 2", dependencies=["step1"])
        .build()
    )

    def runner(task: Task) -> TaskResult:
        return TaskResult(ok=True, output=f"done-{task.task_id}")

    run_id = run_workflow(
        workflow=wf,
        task_states={},
        time_source=time.time,
        task_runner=runner,
        conn=conn,
    )

    spans = extract_run_spans(conn, run_id)
    assert len(spans) == 3  # 1 root workflow span + 2 task spans

    chrome_trace = TraceExporter.to_chrome_trace(conn, run_id)
    assert "traceEvents" in chrome_trace
    assert len(chrome_trace["traceEvents"]) == 3
    assert chrome_trace["displayTimeUnit"] == "ms"

    otel_trace = TraceExporter.to_otel_trace(conn, run_id)
    assert "resourceSpans" in otel_trace
