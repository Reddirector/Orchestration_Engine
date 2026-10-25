"""
Comprehensive tests for real-world production use cases:
- RAG Document Ingestion & Vector Indexing Pipeline
- Automated Incident Triage & Remediation Pipeline
"""

from __future__ import annotations

import time
from typing import Any

from examples.incident_triage import (
    build_incident_triage_workflow,
    incident_triage_runner,
)
from examples.rag_document_indexer import (
    build_rag_indexing_workflow,
    rag_indexer_runner,
)
from orchestration_engine import (
    RetryPolicy,
    Task,
    TaskResult,
    TaskState,
    WorkflowBuilder,
    WorkflowStatus,
    get_connection,
    get_run_history,
    get_run_status,
    run_workflow,
)


def test_rag_document_indexer_e2e_success() -> None:
    """Tests the full RAG document indexer pipeline running to completion."""
    conn = get_connection(":memory:")
    workflow = build_rag_indexing_workflow()

    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=rag_indexer_runner,
        conn=conn,
        max_concurrency=2,
    )

    status = get_run_status(conn, run_id)
    assert status == WorkflowStatus.SUCCEEDED

    # Check task outputs stored in database
    cursor = conn.execute(
        "SELECT task_id, output_json FROM task_outputs WHERE run_id = ? ORDER BY task_id",
        (run_id,),
    )
    outputs = {row[0]: row[1] for row in cursor.fetchall()}
    assert "fetch-docs" in outputs
    assert "chunk-docs" in outputs
    assert "embed-chunks" in outputs
    assert "index-vectors" in outputs
    assert "evaluate-coverage" in outputs
    assert '"HEALTHY"' in outputs["evaluate-coverage"]


def test_rag_document_indexer_embedding_failure_terminates_gracefully() -> None:
    """Tests RAG pipeline behavior when embedding service fails permanently."""
    conn = get_connection(":memory:")
    builder = WorkflowBuilder("rag-fail-test")
    builder.task("fetch-docs")
    builder.task("chunk-docs", dependencies=["fetch-docs"])
    builder.task(
        "embed-chunks",
        dependencies=["chunk-docs"],
        retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0.1),
    )
    builder.task("index-vectors", dependencies=["embed-chunks"])
    workflow = builder.build()

    def failing_runner(task: Task) -> TaskResult:
        if task.task_id == "embed-chunks":
            return TaskResult(ok=False, error="Permanent 500 error from embedding model")
        return rag_indexer_runner(task)

    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=failing_runner,
        conn=conn,
    )

    status = get_run_status(conn, run_id)
    assert status == WorkflowStatus.FAILED

    history = get_run_history(conn, run_id)
    states = {ev[2]: ev[4] for ev in history}
    assert states["embed-chunks"] == TaskState.FAILED.value
    # Dependent task should be cancelled
    assert states["index-vectors"] == TaskState.CANCELLED.value


def test_incident_triage_e2e_success() -> None:
    """Tests the automated incident triage pipeline under concurrency."""
    conn = get_connection(":memory:")
    workflow = build_incident_triage_workflow()

    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=incident_triage_runner,
        conn=conn,
        max_concurrency=3,
        executor="thread",
    )

    status = get_run_status(conn, run_id)
    assert status == WorkflowStatus.SUCCEEDED

    cursor = conn.execute(
        "SELECT output_json FROM task_outputs WHERE run_id = ? AND task_id = 'verify-resolution'",
        (run_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert '"incident_status": "RESOLVED"' in row[0]


def test_incident_triage_remediation_failure_cancels_verification() -> None:
    """Tests that if automated remediation fails, downstream verification is cancelled."""
    conn = get_connection(":memory:")
    builder = WorkflowBuilder("incident-fail-test")
    builder.task("ingest-alert")
    builder.task("synthesize-rca", dependencies=["ingest-alert"])
    builder.task(
        "execute-remediation",
        dependencies=["synthesize-rca"],
        retry_policy=RetryPolicy(max_attempts=1, delay_seconds=0.1),
    )
    builder.task("verify-resolution", dependencies=["execute-remediation"])
    workflow = builder.build()

    def fail_remediation_runner(task: Task) -> TaskResult:
        if task.task_id == "execute-remediation":
            return TaskResult(ok=False, error="Insufficient IAM permissions to restart pool")
        return incident_triage_runner(task)

    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=fail_remediation_runner,
        conn=conn,
    )

    status = get_run_status(conn, run_id)
    assert status == WorkflowStatus.FAILED

    history = get_run_history(conn, run_id)
    states = {ev[2]: ev[4] for ev in history}
    assert states["execute-remediation"] == TaskState.FAILED.value
    assert states["verify-resolution"] == TaskState.CANCELLED.value


def test_incident_triage_multi_source_data_flow() -> None:
    """Verifies that task.inputs correctly accumulates inputs from all three diagnostic tasks."""
    conn = get_connection(":memory:")
    workflow = build_incident_triage_workflow()

    received_inputs: dict[str, Any] = {}

    def inspecting_runner(task: Task) -> TaskResult:
        if task.task_id == "synthesize-rca":
            nonlocal received_inputs
            received_inputs = dict(task.inputs)
        return incident_triage_runner(task)

    run_id = run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=inspecting_runner,
        conn=conn,
        max_concurrency=3,
    )

    assert get_run_status(conn, run_id) == WorkflowStatus.SUCCEEDED
    assert "check-logs" in received_inputs
    assert "check-db-pool" in received_inputs
    assert "check-dependencies" in received_inputs
    assert received_inputs["check-db-pool"]["utilization_pct"] == 100.0
