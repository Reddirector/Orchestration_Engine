import sqlite3
from pathlib import Path

from orchestration_engine.persistence import (
    get_connection,
    get_run_history,
    get_workflow_history,
)


def test_schema_v1_fresh_db(tmp_path: Path) -> None:
    db_file = tmp_path / "fresh.db"
    conn = get_connection(db_file)
    try:
        cur = conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == 1

        # Check runs table
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'")
        assert cur.fetchone() is not None

        # Check task_events columns
        cur = conn.execute("PRAGMA table_info(task_events)")
        cols = {row[1] for row in cur.fetchall()}
        assert {"run_id", "next_retry_at", "error"}.issubset(cols)

        # Check indexes
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        idx_names = {row[0] for row in cur.fetchall()}
        assert "idx_task_events_run" in idx_names
        assert "idx_task_events_wf" in idx_names
    finally:
        conn.close()


def test_migration_v0_to_v1(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy.db"
    # Create a legacy v0 database manually
    raw_conn = sqlite3.connect(db_file)
    raw_conn.execute(
        """
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            old_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            timestamp REAL NOT NULL,
            attempt_count INTEGER NOT NULL
        )
        """
    )
    raw_conn.execute(
        """
        INSERT INTO task_events (
            workflow_id, task_id, old_state, new_state, timestamp, attempt_count
        ) VALUES ('wf-legacy', 'task-1', 'pending', 'ready', 100.0, 0)
        """
    )
    raw_conn.commit()
    raw_conn.close()

    # Open with engine
    conn = get_connection(db_file)
    try:
        cur = conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == 1

        # Check legacy row got migrated run_id
        cur = conn.execute("SELECT run_id FROM task_events WHERE task_id = 'task-1'")
        assert cur.fetchone()[0] == "legacy-wf-legacy"

        # Check get_workflow_history maintains 7-tuple shape
        history = get_workflow_history(conn, "wf-legacy")
        assert len(history) == 1
        assert len(history[0]) == 7
        assert history[0] == (1, "wf-legacy", "task-1", "pending", "ready", 100.0, 0)

        # Check get_run_history returns matching rows
        run_hist = get_run_history(conn, "legacy-wf-legacy")
        assert len(run_hist) == 1
        assert run_hist[0] == (1, "wf-legacy", "task-1", "pending", "ready", 100.0, 0)
    finally:
        conn.close()


def test_connection_hardening(tmp_path: Path) -> None:
    file_db = tmp_path / "hardened.db"
    conn_file = get_connection(file_db)
    try:
        cur = conn_file.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].lower() == "wal"
        cur = conn_file.execute("PRAGMA synchronous")
        assert cur.fetchone()[0] == 1  # 1 = NORMAL
        cur = conn_file.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1  # 1 = ON
        cur = conn_file.execute("PRAGMA busy_timeout")
        assert cur.fetchone()[0] == 5000
    finally:
        conn_file.close()

    conn_mem = get_connection(":memory:")
    try:
        cur = conn_mem.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].lower() == "memory"
        cur = conn_mem.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1
        cur = conn_mem.execute("PRAGMA busy_timeout")
        assert cur.fetchone()[0] == 5000
    finally:
        conn_mem.close()


def test_run_id_plumbing(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
    from orchestration_engine.runner import run_workflow

    task = Task("t1", "wf1", "task 1", "desc", [], TaskState.PENDING, RetryPolicy(1, 1))
    wf = Workflow("wf1", "wf", "desc", [task])

    # 1. run_workflow returns generated run_id
    run_id_1 = run_workflow(wf, {}, lambda: 100.0, lambda _t: True, conn)
    assert isinstance(run_id_1, str)
    assert len(run_id_1) == 32

    # Check runs table
    cur = conn.execute(
        "SELECT run_id, workflow_id, started_at, finished_at, status FROM runs WHERE run_id = ?",
        (run_id_1,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == run_id_1
    assert row[1] == "wf1"
    assert row[2] == 100.0
    assert row[3] == 100.0
    assert row[4] == "succeeded"

    # Check task_events tagged with run_id
    cur = conn.execute("SELECT run_id FROM task_events WHERE run_id = ?", (run_id_1,))
    events = cur.fetchall()
    assert len(events) >= 2  # PENDING->READY, READY->RUNNING, RUNNING->SUCCEEDED

    # 2. Explicit run_id
    task2 = Task("t1", "wf1", "task 1", "desc", [], TaskState.PENDING, RetryPolicy(1, 1))
    wf2 = Workflow("wf1", "wf", "desc", [task2])
    run_id_2 = run_workflow(
        wf2, {}, lambda: 200.0, lambda _t: True, conn, run_id="custom-run-001"
    )
    assert run_id_2 == "custom-run-001"

    cur = conn.execute("SELECT status FROM runs WHERE run_id = 'custom-run-001'")
    assert cur.fetchone()[0] == "succeeded"

    # Verify both runs exist separately in get_run_history
    hist1 = get_run_history(conn, run_id_1)
    hist2 = get_run_history(conn, "custom-run-001")
    assert len(hist1) > 0
    assert len(hist2) > 0
