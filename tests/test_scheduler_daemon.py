"""Unit tests for IntervalSchedule, CronSchedule, and WorkflowScheduler."""

from __future__ import annotations

import datetime
import time

import pytest

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult, Workflow
from orchestration_engine.scheduler import (
    CronSchedule,
    IntervalSchedule,
    WorkflowScheduler,
)


def test_interval_schedule() -> None:
    sched = IntervalSchedule(15.0)
    assert repr(sched) == "IntervalSchedule(15.0s)"
    assert sched.next_run_after(100.0) == 115.0

    with pytest.raises(ValueError):
        IntervalSchedule(0)
    with pytest.raises(ValueError):
        IntervalSchedule(-5.0)


def test_cron_schedule_parsing() -> None:
    cron = CronSchedule("*/15 9-17 * * 1-5")
    assert "CronSchedule" in repr(cron)
    assert 0 in cron.minute_spec
    assert 15 in cron.minute_spec
    assert 30 in cron.minute_spec
    assert 45 in cron.minute_spec
    assert 10 not in cron.minute_spec

    assert 9 in cron.hour_spec
    assert 17 in cron.hour_spec
    assert 8 not in cron.hour_spec

    # Invalid expressions
    with pytest.raises(ValueError):
        CronSchedule("invalid")
    with pytest.raises(ValueError):
        CronSchedule("* * * *")  # 4 fields
    with pytest.raises(ValueError):
        CronSchedule("65 * * * *")  # Out of range minute
    with pytest.raises(ValueError):
        CronSchedule("* * * * */0")  # Step 0


def test_cron_schedule_next_run() -> None:
    # Top of every hour
    cron = CronSchedule("0 * * * *")
    ref_dt = datetime.datetime(2026, 1, 1, 12, 15, 0)
    next_ts = cron.next_run_after(ref_dt.timestamp())
    next_dt = datetime.datetime.fromtimestamp(next_ts)

    assert next_dt.hour == 13
    assert next_dt.minute == 0


def test_workflow_scheduler_tick_and_lifecycle(tmp_path: pytest.TempPathFactory) -> None:
    db = str(tmp_path) + "/sched.db"
    now_virtual = 1000.0

    def time_src() -> float:
        return now_virtual

    sched = WorkflowScheduler(check_interval=0.01, time_source=time_src)

    def wf_factory() -> Workflow:
        return (
            WorkflowBuilder("scheduled-wf")
            .task("ping", name="Ping")
            .build()
        )

    def runner(t: Task) -> TaskResult:
        return TaskResult(ok=True, output="pong")

    job = sched.add_job(
        job_id="hourly-ping",
        workflow_factory=wf_factory,
        schedule=IntervalSchedule(60.0),
        task_runner=runner,
        db_path=db,
    )

    assert job.next_run_at == 1060.0
    assert len(sched.list_jobs()) == 1

    # Before due time: no tick trigger
    triggered = sched.tick(now_virtual)
    assert triggered == []

    # Advance time to due time
    now_virtual = 1065.0
    triggered = sched.tick(now_virtual)
    assert triggered == ["hourly-ping"]
    assert job.runs_count == 1
    assert job.next_run_at == 1125.0

    # Start and stop daemon
    sched.start(daemon=True)
    time.sleep(0.05)
    sched.stop()

    # Remove job
    assert sched.remove_job("hourly-ping") is True
    assert sched.remove_job("nonexistent") is False
    assert len(sched.list_jobs()) == 0
