"""Tests for Durable Timers and Workflow Sleep."""

from __future__ import annotations

import time
from typing import Any

from orchestration_engine.durable_sleep import (
    DURABLE_SLEEP_KEY,
    TimerStatus,
    TimerStore,
    create_sleep_marker,
)


def test_timer_store_create_and_get(tmp_path: Any) -> None:
    db = str(tmp_path / "timers.db")
    store = TimerStore(db)

    timer = store.create_timer(
        run_id="run-1",
        task_id="task-sleep",
        delay_seconds=10.0,
        payload={"reason": "cooling_period"},
    )

    assert timer.run_id == "run-1"
    assert timer.task_id == "task-sleep"
    assert timer.status == TimerStatus.ACTIVE
    assert timer.payload == {"reason": "cooling_period"}
    assert timer.fire_at > timer.created_at
    assert not timer.is_due

    retrieved = store.get_timer(timer.timer_id)
    assert retrieved is not None
    assert retrieved.timer_id == timer.timer_id
    assert retrieved.payload == {"reason": "cooling_period"}


def test_timer_store_due_and_fire(tmp_path: Any) -> None:
    db = str(tmp_path / "timers.db")
    store = TimerStore(db)

    # Timer 1: already due (0 delay)
    t1 = store.create_timer(run_id="run-1", task_id="t1", delay_seconds=0.0)
    # Timer 2: future delay
    t2 = store.create_timer(run_id="run-1", task_id="t2", delay_seconds=100.0)

    time.sleep(0.01)
    due = store.get_due_timers()
    due_ids = [t.timer_id for t in due]
    assert t1.timer_id in due_ids
    assert t2.timer_id not in due_ids

    # Mark fired
    assert store.mark_timer_fired(t1.timer_id) is True
    # Once fired, it should not appear in due list
    assert t1.timer_id not in [t.timer_id for t in store.get_due_timers()]
    # Second fire call returns False
    assert store.mark_timer_fired(t1.timer_id) is False


def test_timer_store_cancellation(tmp_path: Any) -> None:
    db = str(tmp_path / "timers.db")
    store = TimerStore(db)

    t1 = store.create_timer(run_id="run-1", task_id="t1", delay_seconds=5.0)
    store.create_timer(run_id="run-1", task_id="t2", delay_seconds=5.0)
    t3 = store.create_timer(run_id="run-2", task_id="t3", delay_seconds=5.0)

    # Cancel individual
    assert store.cancel_timer(t1.timer_id) is True
    t1_retrieved = store.get_timer(t1.timer_id)
    assert t1_retrieved is not None
    assert t1_retrieved.status == TimerStatus.CANCELLED

    # Cancel all for run-1
    cancelled_count = store.cancel_timers_for_run("run-1")
    assert cancelled_count == 1  # only t2 was still active

    # t3 for run-2 remains active
    t3_retrieved = store.get_timer(t3.timer_id)
    assert t3_retrieved is not None
    assert t3_retrieved.status == TimerStatus.ACTIVE


def test_create_sleep_marker() -> None:
    marker = create_sleep_marker(42.5, {"step": "verification"})
    assert marker[DURABLE_SLEEP_KEY] is True
    assert marker["delay_seconds"] == 42.5
    assert marker["payload"] == {"step": "verification"}
