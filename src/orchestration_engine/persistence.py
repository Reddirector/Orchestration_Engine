import json
import logging
import os
import sqlite3
import time
from typing import Any

from orchestration_engine.errors import OrchestrationError, PersistenceError

logger = logging.getLogger("orchestration_engine")

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

    if current_version < 2:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_outputs (
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                output_json TEXT,
                error TEXT,
                PRIMARY KEY (run_id, task_id),
                FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_outputs_run ON task_outputs (run_id)"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()


def save_task_output(
    conn: sqlite3.Connection,
    run_id: str,
    task_id: str,
    output_json: str | None,
    error: str | None,
) -> None:
    """
    Save or update the output of a task execution in the task_outputs table.
    """
    cursor = conn.execute("PRAGMA user_version")
    if cursor.fetchone()[0] < 2:
        _migrate_database(conn)

    conn.execute(
        """
        INSERT INTO task_outputs (run_id, task_id, output_json, error)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id, task_id) DO UPDATE SET
            output_json = excluded.output_json,
            error = excluded.error
        """,
        (run_id, task_id, output_json, error),
    )
    conn.commit()


def get_task_outputs(
    conn: sqlite3.Connection,
    run_id: str,
) -> dict[str, Any]:
    """
    Retrieve all persisted task outputs for a run.
    """
    cursor = conn.execute("PRAGMA user_version")
    if cursor.fetchone()[0] < 2:
        _migrate_database(conn)

    cursor = conn.execute(
        "SELECT task_id, output_json FROM task_outputs WHERE run_id = ?",
        (run_id,),
    )
    outputs: dict[str, Any] = {}
    for task_id, output_json in cursor.fetchall():
        if output_json is not None:
            try:
                outputs[task_id] = json.loads(output_json)
            except Exception:
                outputs[task_id] = output_json
        else:
            outputs[task_id] = None
    return outputs


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
        logger.error(
            "Persistence failure initializing database at %s: %s",
            target_path,
            e,
            extra={
                "workflow_id": None,
                "run_id": None,
                "task_id": None,
                "old_state": None,
                "new_state": None,
                "attempt": None,
            },
        )
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
        logger.error(
            "Persistence failure logging task event for %s: %s",
            task_id,
            e,
            extra={
                "workflow_id": workflow_id,
                "run_id": run_id,
                "task_id": task_id,
                "old_state": old_state,
                "new_state": new_state,
                "attempt": attempt_count,
            },
        )
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


def list_runs(
    conn: sqlite3.Connection,
    workflow_id: str | None = None,
) -> list[tuple[Any, ...]]:
    """
    List run summaries from the database, ordered newest first.
    Each tuple is (run_id, workflow_id, started_at, finished_at, status).
    """
    _migrate_database(conn)
    if workflow_id is not None:
        cursor = conn.execute(
            """
            SELECT run_id, workflow_id, started_at, finished_at, status
            FROM runs
            WHERE workflow_id = ?
            ORDER BY started_at DESC, run_id DESC
            """,
            (workflow_id,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT run_id, workflow_id, started_at, finished_at, status
            FROM runs
            ORDER BY started_at DESC, run_id DESC
            """
        )
    return cursor.fetchall()


def force_complete_task(
    conn: sqlite3.Connection,
    run_id: str,
    task_id: str,
    output: Any = None,
    reason: str = "Force completed by AI",
) -> None:
    """
    Force/false-complete a task by overriding its state to succeeded with synthetic output.

    Useful for AI-assisted human intervention, self-healing, and simulated completion.
    """
    _migrate_database(conn)
    cursor = conn.cursor()

    cursor.execute("SELECT workflow_id FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    if not row:
        raise OrchestrationError(f"Run '{run_id}' not found.")
    wf_id = row[0]

    # Get latest state and attempt count
    cursor.execute(
        """
        SELECT new_state, attempt_count FROM task_events
        WHERE run_id = ? AND task_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (run_id, task_id),
    )
    ev_row = cursor.fetchone()
    old_state = ev_row[0] if ev_row else "pending"
    attempts = (ev_row[1] if ev_row else 0) + 1

    now = time.time()
    effective_output = (
        output
        if output is not None
        else {
            "completed_by": "ai_fallback",
            "simulated": True,
            "reason": reason,
            "timestamp": now,
        }
    )
    payload_str = json.dumps(effective_output)

    # 1. Insert transition event to succeeded
    conn.execute(
        """
        INSERT INTO task_events
        (run_id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count, error)
        VALUES (?, ?, ?, ?, 'succeeded', ?, ?, NULL)
        """,
        (run_id, wf_id, task_id, old_state, now, attempts),
    )

    # 2. Insert/replace output in task_outputs
    conn.execute(
        """
        INSERT INTO task_outputs (run_id, task_id, output_json, error)
        VALUES (?, ?, ?, NULL)
        ON CONFLICT(run_id, task_id) DO UPDATE SET output_json = ?, error = NULL
        """,
        (run_id, task_id, payload_str, payload_str),
    )

    conn.commit()
    logger.info("Task '%s' in run '%s' was force-completed by AI: %s", task_id, run_id, reason)
