"""Tests for Automated SLA Deadlines and Escalations."""

from __future__ import annotations

import pytest

from orchestration_engine.sla import SLAMonitor, SLAPolicy


def test_sla_policy_validation() -> None:
    with pytest.raises(ValueError):
        SLAPolicy(deadline_seconds=0.0)
    with pytest.raises(ValueError):
        SLAPolicy(deadline_seconds=10.0, warning_ratio=0.0)
    with pytest.raises(ValueError):
        SLAPolicy(deadline_seconds=10.0, warning_ratio=1.5)


def test_sla_monitor_warning_and_breach() -> None:
    warnings: list[tuple[str, float, float]] = []
    breaches: list[tuple[str, float, float]] = []

    policy = SLAPolicy(
        deadline_seconds=10.0,
        warning_ratio=0.8,
        on_warning=lambda tid, el, dl: warnings.append((tid, el, dl)),
        on_breach=lambda tid, el, dl: breaches.append((tid, el, dl)),
    )

    monitor = SLAMonitor()
    monitor.register_sla("heavy_task", policy)

    # Start at t=100.0
    monitor.record_start("heavy_task", timestamp=100.0)

    # 1. Check at t=105.0 (5s elapsed) -> no warning, no breach
    res_5s = monitor.check_slas(now=105.0)
    assert len(res_5s) == 0
    assert len(warnings) == 0
    assert len(breaches) == 0

    # 2. Check at t=108.5 (8.5s elapsed >= 8.0s warning threshold) -> warning fires
    res_8s = monitor.check_slas(now=108.5)
    assert len(res_8s) == 0
    assert len(warnings) == 1
    assert warnings[0][0] == "heavy_task"
    assert warnings[0][1] == 8.5
    assert len(breaches) == 0

    # 3. Check at t=111.0 (11s elapsed >= 10s deadline) -> breach fires
    res_11s = monitor.check_slas(now=111.0)
    assert len(res_11s) == 1
    assert len(breaches) == 1
    assert breaches[0][0] == "heavy_task"
    assert breaches[0][1] == 11.0

    # 4. Check again at t=115.0 -> callbacks do not duplicate
    res_15s = monitor.check_slas(now=115.0)
    assert len(res_15s) == 0
    assert len(warnings) == 1
    assert len(breaches) == 1

    # 5. Complete task
    elapsed = monitor.record_completion("heavy_task", timestamp=116.0)
    assert elapsed == 16.0


def test_sla_completion_before_breach() -> None:
    breaches: list[str] = []
    policy = SLAPolicy(
        deadline_seconds=5.0,
        on_breach=lambda tid, el, dl: breaches.append(tid),
    )

    monitor = SLAMonitor()
    monitor.register_sla("fast_task", policy)
    monitor.record_start("fast_task", timestamp=50.0)

    # Finish before deadline
    elapsed = monitor.record_completion("fast_task", timestamp=52.0)
    assert elapsed == 2.0

    # Checking after deadline should not trigger breach for completed task
    new_breaches = monitor.check_slas(now=60.0)
    assert len(new_breaches) == 0
    assert len(breaches) == 0
