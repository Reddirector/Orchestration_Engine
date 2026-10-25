import os
import sqlite3
from typing import Any

DB_PATH = "orchestration.db"


def get_connection(
    path: str | os.PathLike[str] | None = None,
) -> sqlite3.Connection:
    """
    Open a connection to the engine's SQLite database, creating the
    task_events table if it doesn't already exist.

    Precedence:
        1. Explicit path argument
        2. Environment variable ORCHESTRATION_ENGINE_DB
        3. Default DB_PATH ("orchestration.db")
    """
    if path is not None:
        target_path = str(path)
    elif "ORCHESTRATION_ENGINE_DB" in os.environ:
        target_path = os.environ["ORCHESTRATION_ENGINE_DB"]
    else:
        target_path = DB_PATH

    conn = sqlite3.connect(target_path)
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
    query = (
        "INSERT INTO task_events "
        "(workflow_id, task_id, old_state, new_state, timestamp, attempt_count) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    conn.execute(
        query,
        (workflow_id, task_id, old_state, new_state, timestamp, attempt_count),
    )
    conn.commit()


def get_workflow_history(
    conn: sqlite3.Connection,
    workflow_id: str,
) -> list[tuple[Any, ...]]:
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
