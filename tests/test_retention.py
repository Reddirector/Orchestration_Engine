"""Tests for Data Retention, Compaction, and Cold Archiving."""

from __future__ import annotations

import tarfile
import time
from typing import Any

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import TaskResult, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.retention import (
    compact_event_log,
    export_cold_archive,
    vacuum_database,
)
from orchestration_engine.runner import run_workflow


def test_compact_event_log(tmp_path: Any) -> None:
    db = str(tmp_path / "compact.db")
    conn = get_connection(db)

    wf1 = WorkflowBuilder("wf-compact").task("t1").task("t2", dependencies=["t1"]).build()
    wf2 = WorkflowBuilder("wf-compact").task("t1").task("t2", dependencies=["t1"]).build()

    # Run 1: successful
    run_id_1 = run_workflow(wf1, {}, time.time, lambda t: TaskResult(ok=True), conn)
    # Run 2: failed
    run_id_2 = run_workflow(
        wf2, {}, time.time, lambda t: TaskResult(ok=False, error="fail"), conn
    )

    # Count initial events
    initial_events_1 = conn.execute(
        "SELECT count(*) FROM task_events WHERE run_id = ?", (run_id_1,)
    ).fetchone()[0]
    initial_events_2 = conn.execute(
        "SELECT count(*) FROM task_events WHERE run_id = ?", (run_id_2,)
    ).fetchone()[0]
    assert initial_events_1 > 0
    assert initial_events_2 > 0

    # Compact with older_than_seconds=0 and keep_failed=True
    deleted = compact_event_log(conn, older_than_seconds=0.0, keep_failed=True)
    assert deleted == initial_events_1

    # Run 1 events pruned, but run record remains intact
    count_1 = conn.execute(
        "SELECT count(*) FROM task_events WHERE run_id = ?", (run_id_1,)
    ).fetchone()[0]
    assert count_1 == 0
    run_row_1 = conn.execute(
        "SELECT status FROM runs WHERE run_id = ?", (run_id_1,)
    ).fetchone()
    assert run_row_1[0] == WorkflowStatus.SUCCEEDED.value

    # Run 2 events preserved because keep_failed=True
    count_2 = conn.execute(
        "SELECT count(*) FROM task_events WHERE run_id = ?", (run_id_2,)
    ).fetchone()[0]
    assert count_2 == initial_events_2

    conn.close()


def test_export_cold_archive_and_vacuum(tmp_path: Any) -> None:
    db = str(tmp_path / "archive.db")
    conn = get_connection(db)
    archive_path = str(tmp_path / "cold_storage.tar.gz")

    wf = WorkflowBuilder("wf-archive").task("step1").build()
    run_id = run_workflow(
        wf, {}, time.time, lambda t: TaskResult(ok=True, output={"data": 123}), conn
    )

    # Export to tar.gz with delete_from_db=True
    exported = export_cold_archive(
        conn, [run_id], archive_path, delete_from_db=True
    )
    assert exported == 1

    # Verify run is purged from SQLite
    assert (
        conn.execute("SELECT count(*) FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM task_events WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        == 0
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM task_outputs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        == 0
    )

    # Vacuum database
    vacuum_database(conn)

    # Verify tar.gz contents
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        assert f"runs/{run_id}.json" in names

    conn.close()
