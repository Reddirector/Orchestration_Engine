"""Tests for Time-Travel Inspection and Workflow Replay."""

from __future__ import annotations

import time
from typing import Any

import pytest

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import TaskResult, TaskState, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.replay import fork_run_from_task, time_travel_inspect
from orchestration_engine.runner import resume_run, run_workflow


def test_time_travel_inspect_and_fork(tmp_path: Any) -> None:
    db = str(tmp_path / "replay.db")
    conn = get_connection(db)

    # 1. Build a 3-task pipeline: extract -> transform -> load
    wf = (
        WorkflowBuilder("replay-wf")
        .task("extract")
        .task("transform", dependencies=["extract"])
        .task("load", dependencies=["transform"])
        .build()
    )

    call_counts: dict[str, int] = {"extract": 0, "transform": 0, "load": 0}

    def failing_runner(task: Any) -> Any:
        call_counts[task.task_id] += 1
        if task.task_id == "extract":
            return TaskResult(ok=True, output={"data": [1, 2, 3]})
        elif task.task_id == "transform":
            # Simulate failure
            return TaskResult(ok=False, error="Transform parsing exception")
        return TaskResult(ok=True)

    # Run original workflow (fails at transform)
    run_id = run_workflow(wf, {}, time.time, failing_runner, conn)
    assert call_counts["extract"] == 1
    assert call_counts["transform"] > 0
    assert call_counts["load"] == 0

    # 2. Time-travel inspection
    snapshot_full = time_travel_inspect(conn, run_id)
    assert snapshot_full.workflow_id == "replay-wf"
    assert snapshot_full.task_states["extract"] == TaskState.SUCCEEDED.value
    assert snapshot_full.task_states["transform"] == TaskState.FAILED.value
    assert snapshot_full.task_outputs["extract"] == {"data": [1, 2, 3]}

    # Time-travel back to step 2 (when extract was RUNNING)
    snapshot_early = time_travel_inspect(conn, run_id, at_step=2)
    assert snapshot_early.task_states["extract"] == TaskState.RUNNING.value
    assert "transform" not in snapshot_early.task_states

    # Time-travel back to step 3 (when extract succeeded)
    snapshot_step3 = time_travel_inspect(conn, run_id, at_step=3)
    assert snapshot_step3.task_states["extract"] == TaskState.SUCCEEDED.value

    # 3. Fork run from 'transform'
    forked_run_id = fork_run_from_task(conn, run_id, restart_from_task_id="transform")
    assert forked_run_id != run_id

    # Verify forked run has extract preserved
    forked_snapshot = time_travel_inspect(conn, forked_run_id)
    assert forked_snapshot.task_states["extract"] == TaskState.SUCCEEDED.value
    assert forked_snapshot.task_outputs["extract"] == {"data": [1, 2, 3]}
    assert "transform" not in forked_snapshot.task_states

    # 4. Resume/execute the forked run with a corrected runner
    def fixed_runner(task: Any) -> Any:
        call_counts[task.task_id] += 1
        if task.task_id == "transform":
            # extract output should be present in task.inputs
            data = task.inputs["extract"]["data"]
            return TaskResult(ok=True, output={"transformed": [x * 2 for x in data]})
        return TaskResult(ok=True, output="loaded")

    # Resume the forked run
    resumed_status = resume_run(conn, forked_run_id, fixed_runner, time.time)
    assert resumed_status == WorkflowStatus.SUCCEEDED

    # Extract was NOT re-run in the forked execution!
    assert call_counts["extract"] == 1
    assert call_counts["load"] == 1

    conn.close()


def test_time_travel_inspect_errors(tmp_path: Any) -> None:
    db = str(tmp_path / "replay_err.db")
    conn = get_connection(db)

    with pytest.raises(Exception) as exc_info:
        time_travel_inspect(conn, "nonexistent-run")
    assert "No events found" in str(exc_info.value)

    with pytest.raises(Exception) as exc_info2:
        fork_run_from_task(conn, "nonexistent-run", "task-a")
    assert "Source run 'nonexistent-run' not found" in str(exc_info2.value)

    conn.close()
