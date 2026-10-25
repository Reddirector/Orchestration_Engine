import os
import sqlite3
from typing import Any

from orchestration_engine.errors import PersistenceError

DB_PATH = "orchestration.db"


def _migrate_database(conn: sqlite3.Connection) -> None:
    """
    Ensure the database schema is at the current version (v1),
    applying transactional, idempotent migrations as needed.
    """
    cursor = conn.execute("PRAGMA user_version")
    current_version = cursor.fetchone()[0]

    if current_version < 1:
        # Check if legacy task_events exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='task_events'"
        )
        has_task_events = cursor.fetchone() is not None

        if has_task_events:
            cursor = conn.execute("PRAGMA table_info(task_events)")
            cols = {row[1] for row in cursor.fetchall()}
            if "run_id" not in cols:
                conn.execute("ALTER TABLE task_events ADD COLUMN run_id TEXT")
            if "next_retry_at" not in cols:
                conn.execute("ALTER TABLE task_events ADD COLUMN next_retry_at REAL")
            if "error" not in cols:
                conn.execute("ALTER TABLE task_events ADD COLUMN error TEXT")
            conn.execute(
                "UPDATE task_events SET run_id = 'legacy-' || workflow_id WHERE run_id IS NULL"
            )
        else:
            conn.execute(
                """
                CREATE TABLE task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    old_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    run_id TEXT,
                    next_retry_at REAL,
                    error TEXT
                )
                """
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL,
                status TEXT NOT NULL,
                definition_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_run ON task_events(run_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_wf ON task_events(workflow_id)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()


def get_connection(
    path: str | os.PathLike[str] | None = None,
) -> sqlite3.Connection:
    """
    Open a connection to the engine's SQLite database, creating or migrating
    the schema to the current version.

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

    try:
        conn = sqlite3.connect(target_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        if target_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        _migrate_database(conn)
        return conn
    except sqlite3.Error as e:
        raise PersistenceError(f"Failed to initialize database at {target_path}: {e}") from e


def log_task_event(
    conn: sqlite3.Connection,
    workflow_id: str,
    task_id: str,
    old_state: str,
    new_state: str,
    timestamp: float,
    attempt_count: int,
    run_id: str | None = None,
    next_retry_at: float | None = None,
    error: str | None = None,
) -> None:
    """
    Append a task state transition event to the task_events audit table.
    Raises PersistenceError if the database write fails.
    """
    cursor = conn.execute("PRAGMA user_version")
    if cursor.fetchone()[0] < 1:
        _migrate_database(conn)

    query = (
        "INSERT INTO task_events "
        "(workflow_id, task_id, old_state, new_state, timestamp, attempt_count, "
        "run_id, next_retry_at, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    try:
        conn.execute(
            query,
            (
                workflow_id,
                task_id,
                old_state,
                new_state,
                timestamp,
                attempt_count,
                run_id,
                next_retry_at,
                error,
            ),
        )
        conn.commit()
    except sqlite3.Error as e:
        raise PersistenceError(f"Failed to log task event for {task_id}: {e}") from e


def get_workflow_history(
    conn: sqlite3.Connection,
    workflow_id: str,
) -> list[tuple[Any, ...]]:
    """
    Return every logged task-state transition for a workflow, ordered by
    timestamp, id. Each row is (id, workflow_id, task_id, old_state, new_state,
    timestamp, attempt_count).
    """
    cursor = conn.execute(
        """
        SELECT id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count
        FROM task_events
        WHERE workflow_id = ?
        ORDER BY timestamp, id
        """,
        (workflow_id,),
    )
    return cursor.fetchall()


def get_run_history(
    conn: sqlite3.Connection,
    run_id: str,
) -> list[tuple[Any, ...]]:
    """
    Return every logged task-state transition for a single run, ordered by
    timestamp, id. Each row is (id, workflow_id, task_id, old_state, new_state,
    timestamp, attempt_count).
    """
    cursor = conn.execute(
        """
        SELECT id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count
        FROM task_events
        WHERE run_id = ?
        ORDER BY timestamp, id
        """,
        (run_id,),
    )
    return cursor.fetchall()
