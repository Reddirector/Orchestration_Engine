"""Tiered Cold-Archival and SQLite Audit Log Compaction.

Provides production data retention policies, pruning historical microsecond events from
active SQLite tables, exporting full run bundles into compressed .tar.gz cold storage,
and vacuuming database files without third-party dependencies.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
import time
from typing import Any

from orchestration_engine.models import WorkflowStatus


def compact_event_log(
    conn: sqlite3.Connection,
    *,
    older_than_seconds: float,
    keep_failed: bool = True,
) -> int:
    """Prune fine-grained task_events for old completed runs while preserving runs summaries.

    Args:
        conn: Open SQLite connection.
        older_than_seconds: Runs finished more than this many seconds ago are eligible.
        keep_failed: If True, preserves events for failed/cancelled runs for post-mortem triage.

    Returns:
        Number of task_events rows deleted.
    """
    cutoff = time.time() - max(0.0, float(older_than_seconds))

    allowed_statuses = [WorkflowStatus.SUCCEEDED.value]
    if not keep_failed:
        allowed_statuses.extend([WorkflowStatus.FAILED.value, "cancelled"])

    status_placeholders = ",".join("?" for _ in allowed_statuses)
    with conn:
        # 1. Identify eligible run_ids
        cursor = conn.execute(
            f"""
            SELECT run_id FROM runs
            WHERE finished_at IS NOT NULL
              AND finished_at <= ?
              AND status IN ({status_placeholders})
            """,  # noqa: S608
            (cutoff, *allowed_statuses),
        )
        eligible_runs = [row[0] for row in cursor.fetchall()]
        if not eligible_runs:
            return 0

        # 2. Delete task_events for those runs
        run_placeholders = ",".join("?" for _ in eligible_runs)
        del_cursor = conn.execute(
            f"DELETE FROM task_events WHERE run_id IN ({run_placeholders})",  # noqa: S608
            eligible_runs,
        )
        return del_cursor.rowcount


def export_cold_archive(
    conn: sqlite3.Connection,
    run_ids: list[str],
    output_tar_path: str,
    *,
    delete_from_db: bool = False,
) -> int:
    """Export specified workflow runs into a compressed .tar.gz archive.

    Args:
        conn: Open SQLite connection.
        run_ids: List of run_ids to bundle into archive.
        output_tar_path: Destination path for .tar.gz file.
        delete_from_db: If True, deletes archived runs, events, and outputs from SQLite.

    Returns:
        Number of runs successfully written to archive.
    """
    if not run_ids:
        return 0

    archived_count = 0
    with tarfile.open(output_tar_path, "w:gz") as tar:
        for run_id in run_ids:
            # 1. Fetch run row
            run_cursor = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            run_row = run_cursor.fetchone()
            if not run_row:
                continue

            run_cols = [desc[0] for desc in run_cursor.description]
            run_data = dict(zip(run_cols, run_row, strict=False))

            # 2. Fetch events
            evt_cursor = conn.execute(
                "SELECT * FROM task_events WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            )
            evt_cols = [desc[0] for desc in evt_cursor.description]
            events_data = [dict(zip(evt_cols, r, strict=False)) for r in evt_cursor.fetchall()]

            # 3. Fetch outputs
            out_cursor = conn.execute("SELECT * FROM task_outputs WHERE run_id = ?", (run_id,))
            out_cols = [desc[0] for desc in out_cursor.description]
            outputs_data = [dict(zip(out_cols, r, strict=False)) for r in out_cursor.fetchall()]

            bundle: dict[str, Any] = {
                "run": run_data,
                "events": events_data,
                "outputs": outputs_data,
                "archived_at": time.time(),
            }

            raw_bytes = json.dumps(bundle, indent=2).encode("utf-8")
            ti = tarfile.TarInfo(name=f"runs/{run_id}.json")
            ti.size = len(raw_bytes)
            ti.mtime = int(time.time())
            tar.addfile(ti, io.BytesIO(raw_bytes))
            archived_count += 1

    if delete_from_db and archived_count > 0:
        placeholders = ",".join("?" for _ in run_ids)
        with conn:
            conn.execute(
                f"DELETE FROM task_events WHERE run_id IN ({placeholders})",  # noqa: S608
                run_ids,
            )
            conn.execute(
                f"DELETE FROM task_outputs WHERE run_id IN ({placeholders})",  # noqa: S608
                run_ids,
            )
            conn.execute(
                f"DELETE FROM runs WHERE run_id IN ({placeholders})",  # noqa: S608
                run_ids,
            )

    return archived_count


def vacuum_database(conn: sqlite3.Connection) -> None:
    """Execute VACUUM on SQLite database to reclaim disk space after compaction."""
    conn.execute("VACUUM")
