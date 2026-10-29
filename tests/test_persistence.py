
import sqlite3

from orchestration_engine.errors import OrchestrationError
from orchestration_engine.persistence import (
    force_complete_task,
    get_task_outputs,
    get_workflow_history,
    log_task_event,
)


def test_get_workflow_history_returns_events_in_order(conn: sqlite3.Connection) -> None:
    log_task_event(
        conn, workflow_id="wf-1", task_id="task-1",
        old_state="pending", new_state="ready", timestamp=1.0, attempt_count=0,
    )
    log_task_event(
        conn, workflow_id="wf-1", task_id="task-1",
        old_state="ready", new_state="running", timestamp=2.0, attempt_count=1,
    )
    log_task_event(
        conn, workflow_id="wf-2", task_id="task-9",
        old_state="pending", new_state="ready", timestamp=1.5, attempt_count=0,
    )

    history = get_workflow_history(conn, "wf-1")

    assert len(history) == 2
    assert history[0][3] == "pending"
    assert history[1][4] == "running"


def test_force_complete_task(conn: sqlite3.Connection) -> None:
    from orchestration_engine.persistence import _migrate_database
    _migrate_database(conn)
    conn.execute(
        "INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) "
        "VALUES ('run-fc-1', 'wf-fc', 100.0, NULL, 'running', '{}')"
    )
    conn.commit()

    # Force complete task
    force_complete_task(conn, "run-fc-1", "task-block", output={"ai_resolved": True})

    # Verify event logged
    cur = conn.execute(
        "SELECT new_state FROM task_events WHERE run_id = 'run-fc-1' AND task_id = 'task-block'"
    )
    assert cur.fetchone()[0] == "succeeded"

    # Verify output recorded
    outputs = get_task_outputs(conn, "run-fc-1")
    assert outputs["task-block"] == {"ai_resolved": True}

    # Error on nonexistent run
    import pytest
    with pytest.raises(OrchestrationError):
        force_complete_task(conn, "nonexistent-run", "task-x")
