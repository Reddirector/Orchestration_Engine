import sqlite3
from pathlib import Path

import pytest

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


def test_status_from_database(conn: sqlite3.Connection) -> None:
    from orchestration_engine.errors import OrchestrationError
    from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
    from orchestration_engine.persistence import list_runs
    from orchestration_engine.runner import run_workflow
    from orchestration_engine.status import get_run_status

    task1 = Task("t1", "wf1", "task 1", "desc", [], TaskState.PENDING, RetryPolicy(1, 1))
    wf = Workflow("wf1", "wf", "desc", [task1])
    run_id_success = run_workflow(wf, {}, lambda: 100.0, lambda _t: True, conn)
    assert get_run_status(conn, run_id_success) == WorkflowStatus.SUCCEEDED

    task2 = Task("t2", "wf1", "task 2", "desc", [], TaskState.PENDING, RetryPolicy(1, 1))
    wf_fail = Workflow("wf1", "wf", "desc", [task2])
    run_id_fail = run_workflow(wf_fail, {}, lambda: 150.0, lambda _t: False, conn)
    assert get_run_status(conn, run_id_fail) == WorkflowStatus.FAILED

    with pytest.raises(OrchestrationError, match="not found"):
        get_run_status(conn, "nonexistent-run")

    # test list_runs
    runs_all = list_runs(conn)
    assert len(runs_all) == 2
    # newest first
    assert runs_all[0][0] == run_id_fail
    assert runs_all[1][0] == run_id_success

    runs_wf1 = list_runs(conn, workflow_id="wf1")
    assert len(runs_wf1) == 2

    runs_wf2 = list_runs(conn, workflow_id="nonexistent-wf")
    assert len(runs_wf2) == 0


def test_g6_single_source_of_truth_mirror(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
    from orchestration_engine.runner import run_workflow

    current_time = 100.0

    def adv_time() -> float:
        return current_time

    def fake_sleep(s: float) -> None:
        nonlocal current_time
        current_time += s

    t1 = Task("t1", "wf", "Success", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    t2 = Task("t2", "wf", "RetrySuccess", "d", [], TaskState.PENDING, RetryPolicy(3, 1.0))
    t3 = Task("t3", "wf", "ExceptionFail", "d", [], TaskState.PENDING, RetryPolicy(2, 1.0))
    t4 = Task("t4", "wf", "Dependent", "d", ["t3"], TaskState.PENDING, RetryPolicy(1, 1.0))
    t5 = Task("t5", "wf", "Transitive", "d", ["t4"], TaskState.PENDING, RetryPolicy(1, 1.0))
    t6 = Task(
        "t6",
        "wf",
        "TimeoutTask",
        "d",
        [],
        TaskState.PENDING,
        RetryPolicy(1, 1.0),
        timeout_seconds=0.1,
    )

    wf = Workflow("wf", "Workflow", "desc", [t1, t2, t3, t4, t5, t6])
    task_states: dict[str, TaskState] = {}

    attempts: dict[str, int] = {}

    def runner(task: Task) -> bool:
        nonlocal current_time
        attempts[task.task_id] = attempts.get(task.task_id, 0) + 1
        if task.task_id == "t1":
            return True
        elif task.task_id == "t2":
            return attempts[task.task_id] >= 2
        elif task.task_id == "t3":
            raise RuntimeError("Task 3 exploded")
        elif task.task_id == "t6":
            import time
            time.sleep(0.3)
            return True
        return True

    run_workflow(
        wf,
        task_states,
        time_source=adv_time,
        task_runner=runner,
        conn=conn,
        sleep=fake_sleep,
    )

    # Verify varied outcomes
    assert t1.state == TaskState.SUCCEEDED
    assert t2.state == TaskState.SUCCEEDED
    assert t3.state == TaskState.FAILED
    assert t4.state == TaskState.CANCELLED
    assert t5.state == TaskState.CANCELLED
    assert t6.state == TaskState.FAILED

    # Verify mirror is strictly identical for every task
    assert len(task_states) == len(wf.tasks)
    for task in wf.tasks:
        assert task_states[task.task_id] == task.state


def test_resume_run(conn: sqlite3.Connection) -> None:
    from orchestration_engine.loader import load_workflow_from_json
    from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
    from orchestration_engine.runner import resume_run, run_workflow
    from orchestration_engine.transitions import transition_task

    # 1. Resuming finished run returns status and does not invoke runner
    t1 = Task("t1", "wf-res", "T1", "desc", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf-res", "ResumeWF", "desc", [t1])
    run_id = run_workflow(wf, {}, lambda: 100.0, lambda _t: True, conn)

    invoked = False

    def dummy_runner(_t: Task) -> bool:
        nonlocal invoked
        invoked = True
        return True

    res_status = resume_run(conn, run_id, dummy_runner, lambda: 150.0)
    assert res_status == WorkflowStatus.SUCCEEDED
    assert invoked is False

    # 2. Interrupted run: task A succeeded, task B died while RUNNING
    raw_json = {
        "workflow_id": "wf-interrupted",
        "name": "Interrupted WF",
        "description": "desc",
        "tasks": [
            {
                "task_id": "stepA",
                "name": "Step A",
                "description": "desc",
                "dependencies": [],
                "retry_policy": {"max_attempts": 1, "delay_seconds": 1.0},
            },
            {
                "task_id": "stepB",
                "name": "Step B",
                "description": "desc",
                "dependencies": ["stepA"],
                "retry_policy": {"max_attempts": 2, "delay_seconds": 1.0},
            },
        ],
    }
    wf2 = load_workflow_from_json(raw_json)
    run_id2 = "interrupted-run-1"
    # Execute stepA to success, stepB to running, then "crash"
    tA = wf2.tasks[0]
    tB = wf2.tasks[1]
    tA._run_id = run_id2
    tB._run_id = run_id2
    # Record run in DB
    from orchestration_engine.runner import _serialize_workflow
    conn.execute(
        """
        INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json)
        VALUES (?, ?, 100.0, NULL, 'running', ?)
        """,
        (run_id2, "wf-interrupted", _serialize_workflow(wf2)),
    )
    transition_task(tA, TaskState.READY, conn, 100.0)
    tA.attempt_count = 1
    transition_task(tA, TaskState.RUNNING, conn, 101.0)
    transition_task(tA, TaskState.SUCCEEDED, conn, 102.0)
    transition_task(tB, TaskState.READY, conn, 103.0)
    tB.attempt_count = 1
    transition_task(tB, TaskState.RUNNING, conn, 104.0)
    conn.commit()

    # Now resume in the engine
    a_ran = False
    b_ran = False

    def resume_task_runner(task: Task) -> bool:
        nonlocal a_ran, b_ran
        if task.task_id == "stepA":
            a_ran = True
        elif task.task_id == "stepB":
            b_ran = True
        return True

    curr_time = 200.0

    def adv_time() -> float:
        return curr_time

    def fake_sleep(s: float) -> None:
        nonlocal curr_time
        curr_time += s

    final_status = resume_run(
        conn,
        run_id2,
        resume_task_runner,
        time_source=adv_time,
        sleep=fake_sleep,
    )
    assert final_status == WorkflowStatus.SUCCEEDED
    assert a_ran is False  # Never re-run stepA
    assert b_ran is True   # Retried and succeeded stepB

    # Check database history for attempt counts
    hist = get_run_history(conn, run_id2)
    b_events = [ev for ev in hist if ev[2] == "stepB"]
    # Final event for stepB is SUCCEEDED with attempt_count == 2
    assert b_events[-1][4] == "succeeded"
    assert b_events[-1][6] == 2
