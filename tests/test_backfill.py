"""
Unit tests for Historical Backfill & Deterministic Catchup Engine.
"""

from typing import Any

from orchestration_engine.backfill import (
    BackfillExecutor,
    CatchupPolicy,
    generate_backfill_plan,
)
from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.persistence import get_connection


def test_generate_backfill_plan_policies() -> None:
    # 1. CatchupPolicy.ALL
    plan_all = generate_backfill_plan(
        workflow_id="etl-sync",
        start_time=1000.0,
        end_time=1400.0,
        interval_seconds=100.0,
        catchup_policy=CatchupPolicy.ALL,
        jitter_max_seconds=10.0,
    )
    assert len(plan_all.windows) == 4
    assert plan_all.windows[0].start_time == 1000.0
    assert plan_all.windows[0].end_time == 1100.0
    assert 0.0 <= plan_all.windows[0].jitter_seconds <= 10.0

    # 2. CatchupPolicy.LATEST_ONLY
    plan_latest = generate_backfill_plan(
        workflow_id="etl-sync",
        start_time=1000.0,
        end_time=1400.0,
        interval_seconds=100.0,
        catchup_policy=CatchupPolicy.LATEST_ONLY,
    )
    assert len(plan_latest.windows) == 1
    assert plan_latest.windows[0].start_time == 1300.0
    assert plan_latest.windows[0].end_time == 1400.0

    # 3. CatchupPolicy.SLIDING_WINDOW
    plan_sliding = generate_backfill_plan(
        workflow_id="etl-sync",
        start_time=1000.0,
        end_time=1500.0,
        interval_seconds=100.0,
        catchup_policy=CatchupPolicy.SLIDING_WINDOW,
        sliding_window_count=2,
    )
    assert len(plan_sliding.windows) == 2
    assert plan_sliding.windows[0].start_time == 1300.0
    assert plan_sliding.windows[1].start_time == 1400.0


def test_backfill_executor_execution(tmp_path: Any) -> None:
    db_file = str(tmp_path / "backfill.db")
    executor = BackfillExecutor(db_file)

    wf = (
        WorkflowBuilder("historical-etl")
        .task("sync_range", name="Sync Historical Range")
        .build()
    )

    seen_windows: list[dict[str, Any]] = []

    def task_runner(t: Task) -> TaskResult:
        seen_windows.append(
            {
                "window_start": t.inputs.get("window_start"),
                "window_end": t.inputs.get("window_end"),
                "window_id": t.inputs.get("window_id"),
            }
        )
        return TaskResult(ok=True, output={"synced": True})

    plan = generate_backfill_plan(
        workflow_id="historical-etl",
        start_time=0.0,
        end_time=300.0,
        interval_seconds=100.0,
    )

    results = executor.run_plan(
        plan=plan,
        workflow=wf,
        task_runner=task_runner,
        conn_factory=lambda: get_connection(db_file),
    )

    assert len(results) == 3
    assert all(w.status == "SUCCEEDED" for w in results)
    assert len(seen_windows) == 3
    assert seen_windows[0]["window_start"] == 0.0
    assert seen_windows[0]["window_end"] == 100.0
    assert seen_windows[2]["window_start"] == 200.0
    assert seen_windows[2]["window_end"] == 300.0

    # Verify query status
    win_stat = executor.get_window_status(results[0].window_id)
    assert win_stat is not None
    assert win_stat["status"] == "SUCCEEDED"
