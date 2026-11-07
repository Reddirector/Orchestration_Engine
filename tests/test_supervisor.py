"""
Unit tests for Self-Healing Workflow Watchdog & Auto-Supervisor.
"""

from typing import Any

from orchestration_engine.persistence import get_connection
from orchestration_engine.supervisor import (
    AutoRemedy,
    SupervisorPolicy,
    WorkflowSupervisor,
)


def _setup_stuck_run(conn: Any, run_id: str, task_id: str, started_at: float) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, workflow_id, started_at, status, definition_json)
            VALUES (?, 'wf-supervisor', ?, 'running', '{}')
            """,
            (run_id, started_at),
        )
        conn.execute(
            """
            INSERT INTO task_events (
                run_id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count, error
            ) VALUES (?, 'wf-supervisor', ?, 'ready', 'running', ?, 1, NULL)
            """,
            (run_id, task_id, started_at),
        )


def test_supervisor_detect_and_retry(tmp_path: Any) -> None:
    db_file = str(tmp_path / "supervisor_retry.db")
    conn = get_connection(db_file)

    policy = SupervisorPolicy(stuck_timeout_seconds=60.0, default_remedy=AutoRemedy.RETRY)
    supervisor = WorkflowSupervisor(conn, policy)

    # Task started at t=100.0
    _setup_stuck_run(conn, "run_stuck_1", "t_zombie", 100.0)

    # At t=150.0 (50s elapsed) -> not stuck yet
    incidents = supervisor.scan_and_heal(time_source=150.0)
    assert len(incidents) == 0

    # At t=170.0 (70s elapsed >= 60s) -> zombie task!
    incidents = supervisor.scan_and_heal(time_source=170.0)
    assert len(incidents) == 1
    assert incidents[0].task_id == "t_zombie"
    assert incidents[0].remedy_applied == AutoRemedy.RETRY

    # Verify ready event was emitted
    cursor = conn.execute(
        "SELECT new_state FROM task_events WHERE run_id = 'run_stuck_1' ORDER BY id DESC LIMIT 1"
    )
    assert cursor.fetchone()[0] == "ready"


def test_supervisor_escalate_to_abort(tmp_path: Any) -> None:
    db_file = str(tmp_path / "supervisor_abort.db")
    conn = get_connection(db_file)

    policy = SupervisorPolicy(
        stuck_timeout_seconds=50.0,
        default_remedy=AutoRemedy.RETRY,
        max_auto_retries=1,
    )
    supervisor = WorkflowSupervisor(conn, policy)

    _setup_stuck_run(conn, "run_stuck_2", "t_chronic", 100.0)

    # First healing: RETRY (1st retry)
    incidents1 = supervisor.scan_and_heal(time_source=160.0)
    assert len(incidents1) == 1
    assert incidents1[0].remedy_applied == AutoRemedy.RETRY

    # Simulate task running again and getting stuck again at t=200
    with conn:
        conn.execute(
            """
            INSERT INTO task_events (
                run_id, workflow_id, task_id,
                old_state, new_state, timestamp, attempt_count, error
            ) VALUES (
                'run_stuck_2', 'wf-supervisor', 't_chronic',
                'ready', 'running', 200.0, 2, NULL
            )
            """
        )

    # Second healing at t=260: exceeds max_auto_retries=1 -> ABORT_RUN
    incidents2 = supervisor.scan_and_heal(time_source=260.0)
    assert len(incidents2) == 1
    assert incidents2[0].remedy_applied == AutoRemedy.ABORT_RUN

    # Verify run marked failed
    cursor = conn.execute("SELECT status FROM runs WHERE run_id = 'run_stuck_2'")
    assert cursor.fetchone()[0] == "failed"

    history = supervisor.get_incidents("run_stuck_2")
    assert len(history) == 2
