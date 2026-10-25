import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from orchestration_engine.models import Task, WorkflowStatus
from orchestration_engine.persistence import get_connection, get_run_history
from orchestration_engine.runner import resume_run


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL required for crash test")
def test_subprocess_sigkill_crash_and_resume(tmp_path: Path) -> None:
    db_file = tmp_path / "crash_test.db"
    marker_a = tmp_path / "marker_a.done"
    marker_b = tmp_path / "marker_b.started"
    marker_a_rerun = tmp_path / "marker_a.rerun"
    marker_b_done = tmp_path / "marker_b.resumed"
    run_id = "test-sigkill-run-1"

    wf_def = {
        "workflow_id": "wf-crash",
        "name": "Crash Workflow",
        "description": "Testing SIGKILL and resume",
        "tasks": [
            {
                "task_id": "stepA",
                "name": "Step A",
                "description": "First task",
                "dependencies": [],
                "retry_policy": {"max_attempts": 1, "delay_seconds": 0.1},
            },
            {
                "task_id": "stepB",
                "name": "Step B",
                "description": "Second task",
                "dependencies": ["stepA"],
                "retry_policy": {"max_attempts": 2, "delay_seconds": 0.1},
            },
        ],
    }

    child_code = f"""
import sys, time
from pathlib import Path
from orchestration_engine.persistence import get_connection
from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.runner import run_workflow

conn = get_connection({str(db_file)!r})
wf = load_workflow_from_json({json.dumps(wf_def)})

def runner(task):
    if task.task_id == "stepA":
        Path({str(marker_a)!r}).write_text("done")
        return True
    elif task.task_id == "stepB":
        Path({str(marker_b)!r}).write_text("started")
        time.sleep(30.0)
        return True
    return False

run_workflow(wf, {{}}, time.time, runner, conn, run_id={run_id!r})
"""

    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        env=env,
    )

    try:
        # Wait for stepB to write its marker indicating it is RUNNING
        start_wait = time.perf_counter()
        while not marker_b.exists():
            time.sleep(0.05)
            if time.perf_counter() - start_wait > 10.0:
                raise TimeoutError("Child did not start stepB in time")

        # Now SIGKILL the child process while stepB is RUNNING
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()

    # Verify stepA completed and stepB was running before kill
    assert marker_a.exists()
    assert marker_b.exists()

    # Now in the parent process, resume the run using resume_run
    conn = get_connection(db_file)
    try:
        def resume_runner(task: Task) -> bool:
            if task.task_id == "stepA":
                marker_a_rerun.write_text("stepA ran again!")
                return True
            elif task.task_id == "stepB":
                marker_b_done.write_text("resumed and finished")
                return True
            return True

        status = resume_run(conn, run_id, resume_runner, time.time)
        assert status == WorkflowStatus.SUCCEEDED

        # Assert completed tasks were NOT re-run
        assert not marker_a_rerun.exists(), "Completed task stepA was re-run!"

        # Assert interrupted task was retried and completed
        assert marker_b_done.exists()

        # Check run history in SQLite
        history = get_run_history(conn, run_id)
        b_events = [ev for ev in history if ev[2] == "stepB"]
        # stepB should have: READY -> RUNNING (attempt 1) -> RETRY_WAIT (interrupted)
        # -> READY -> RUNNING (attempt 2) -> SUCCEEDED (attempt 2)
        states = [ev[4] for ev in b_events]
        assert "running" in states
        assert "retry_wait" in states
        assert states[-1] == "succeeded"
        assert b_events[-1][6] == 2  # attempt_count 2
    finally:
        conn.close()
