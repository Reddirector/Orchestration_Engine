import sqlite3

DB_PATH = "orchestration.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
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
    conn.commit()
    return conn


def log_task_event(
    conn: sqlite3.Connection,
    workflow_id: str,
    task_id: str,
    old_state: str,
    new_state: str,
    timestamp: float,
    attempt_count: int,
) -> None:
    conn.execute(
        "INSERT INTO task_events (workflow_id, task_id, old_state, new_state, timestamp, attempt_count) VALUES (?, ?, ?, ?, ?, ?)",
        (workflow_id, task_id, old_state, new_state, timestamp, attempt_count),
    )
    conn.commit()


def get_workflow_history(
    conn: sqlite3.Connection,
    workflow_id: str,
) -> list[tuple]:
    cursor = conn.execute(
        "SELECT * FROM task_events WHERE workflow_id = ? ORDER BY timestamp",
        (workflow_id,),
    )
    return cursor.fetchall()


def test_get_workflow_history_returns_events_in_order(conn) -> None:
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
