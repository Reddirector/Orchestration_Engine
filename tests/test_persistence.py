
import sqlite3

from orchestration_engine.persistence import get_workflow_history, log_task_event


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
