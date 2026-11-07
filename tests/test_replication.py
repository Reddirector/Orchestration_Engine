"""Tests for Multi-Node SQLite Replication and CDC Synchronization."""

from __future__ import annotations

from typing import Any

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.persistence import get_connection, get_run_history
from orchestration_engine.replication import (
    CDCBatch,
    CDCEvent,
    CDCOutput,
    CDCReplicationSource,
    CDCReplicationTarget,
    CDCRun,
    ReplicationClient,
    ReplicationServer,
)
from orchestration_engine.runner import run_workflow


def test_cdc_batch_serialization() -> None:
    batch = CDCBatch(
        last_event_id=42,
        runs=[
            CDCRun(
                run_id="run_abc",
                workflow_id="wf_1",
                started_at=100.0,
                finished_at=105.0,
                status="succeeded",
                definition_json="{}",
            )
        ],
        events=[
            CDCEvent(
                event_id=42,
                workflow_id="wf_1",
                task_id="t1",
                old_state="ready",
                new_state="running",
                timestamp=100.0,
                attempt_count=1,
                run_id="run_abc",
            )
        ],
        outputs=[
            CDCOutput(
                run_id="run_abc",
                task_id="t1",
                output_json='{"status": "ok"}',
                error=None,
            )
        ],
    )
    d = batch.to_dict()
    restored = CDCBatch.from_dict(d)
    assert restored.last_event_id == 42
    assert len(restored.runs) == 1
    assert restored.runs[0].run_id == "run_abc"
    assert len(restored.events) == 1
    assert restored.events[0].task_id == "t1"
    assert len(restored.outputs) == 1
    assert restored.outputs[0].output_json == '{"status": "ok"}'


def test_cdc_source_and_target_local_sync(tmp_path: Any) -> None:
    # 1. Primary DB with an executed workflow
    primary_db = str(tmp_path / "primary.db")
    primary_conn = get_connection(primary_db)

    wf = (
        WorkflowBuilder("repl_wf")
        .task("task_1", name="Task 1")
        .task("task_2", name="Task 2", dependencies=["task_1"])
        .build()
    )

    def runner(task: Task) -> TaskResult:
        return TaskResult(ok=True, output={"msg": f"hello from {task.task_id}"})

    run_id = run_workflow(
        workflow=wf,
        task_states={t.task_id: t.state for t in wf.tasks},
        time_source=lambda: 1000.0,
        task_runner=runner,
        conn=primary_conn,
        executor="_inline",
    )

    # 2. Extract CDC batch from primary
    source = CDCReplicationSource(primary_conn)
    batch = source.read_changes(since_event_id=0, limit=50)

    assert len(batch.events) >= 4  # (pending->ready, ready->running, running->succeeded)
    assert len(batch.outputs) == 2  # task_1 and task_2 outputs
    assert batch.last_event_id > 0

    # 3. Apply to fresh replica DB
    replica_db = str(tmp_path / "replica.db")
    replica_conn = get_connection(replica_db)
    target = CDCReplicationTarget(replica_conn)

    applied_count = target.apply_batch(batch)
    assert applied_count == len(batch.events)
    assert target.get_last_synced_event_id() == batch.last_event_id

    # Verify replica has identical history
    repl_hist = get_run_history(replica_conn, run_id)
    prim_hist = get_run_history(primary_conn, run_id)
    assert repl_hist == prim_hist


def test_cdc_http_replication_e2e(tmp_path: Any) -> None:
    primary_db = str(tmp_path / "http_primary.db")
    replica_db = str(tmp_path / "http_replica.db")

    primary_conn = get_connection(primary_db)

    # Populate primary
    wf = (
        WorkflowBuilder("http_repl_wf")
        .task("fetch", name="Fetch")
        .build()
    )
    run_workflow(
        workflow=wf,
        task_states={t.task_id: t.state for t in wf.tasks},
        time_source=lambda: 1000.0,
        task_runner=lambda t: TaskResult(ok=True, output={"status": "ok"}),
        conn=primary_conn,
        executor="_inline",
    )

    # Start HTTP server on dynamic port
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    server = ReplicationServer(db_path=primary_db, host="127.0.0.1", port=port)
    server.start()

    try:
        client = ReplicationClient(
            replica_conn_or_path=replica_db,
            primary_url=f"http://127.0.0.1:{port}",
        )
        synced = client.sync_once()
        assert synced >= 2  # events synced

        # Second sync has nothing new
        synced_again = client.sync_once()
        assert synced_again == 0
    finally:
        server.stop()
