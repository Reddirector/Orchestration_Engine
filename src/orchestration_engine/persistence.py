import sqlite3

DB_PATH = "orchestration.db"


def get_connection() -> sqlite3.Connection:
    """
    Open a connection to the engine's SQLite database, creating the
    task_events table if it doesn't already exist.
    """
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
    """
    Return every logged task-state transition for a workflow, ordered by
    timestamp. Each row is (id, workflow_id, task_id, old_state, new_state,
    timestamp, attempt_count).
    """
    cursor = conn.execute(
        "SELECT * FROM task_events WHERE workflow_id = ? ORDER BY timestamp",
        (workflow_id,),
    )
    return cursor.fetchall()
