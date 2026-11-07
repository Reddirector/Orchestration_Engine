"""Tests for Adaptive Concurrency Control and Backpressure Feedback Loops."""

from __future__ import annotations

from unittest.mock import patch

from orchestration_engine.adaptive import (
    AdaptiveConcurrencyController,
    AdaptiveConcurrencyPolicy,
)


def test_aimd_additive_increase_and_multiplicative_decrease() -> None:
    policy = AdaptiveConcurrencyPolicy(
        min_concurrency=2,
        max_concurrency=10,
        initial_concurrency=4,
        backoff_factor=0.5,
        step_increase=2,
        latency_threshold_seconds=1.0,
    )
    ctrl = AdaptiveConcurrencyController(policy)
    assert ctrl.current_concurrency == 4

    # 1. Nominal latency -> Additive increase
    c1 = ctrl.record_success(latency_seconds=0.2)
    assert c1 == 6

    c2 = ctrl.record_success(latency_seconds=0.3)
    assert c2 == 8

    c3 = ctrl.record_success(latency_seconds=0.1)
    assert c3 == 10  # Clamped to max_concurrency

    # 2. Failure occurs -> Multiplicative decrease
    c4 = ctrl.record_failure(is_transient=True)
    assert c4 == 5  # 10 * 0.5 = 5

    c5 = ctrl.record_failure(is_transient=True)
    assert c5 == 2  # 5 * 0.5 = 2.5 -> int 2 (clamped to min_concurrency 2)


def test_high_latency_and_cpu_load_backpressure() -> None:
    policy = AdaptiveConcurrencyPolicy(
        min_concurrency=1,
        max_concurrency=10,
        initial_concurrency=6,
        step_increase=1,
        latency_threshold_seconds=1.5,
        max_cpu_load=4.0,
    )
    ctrl = AdaptiveConcurrencyController(policy)

    # Latency above threshold causes gentle step-down
    c1 = ctrl.record_success(latency_seconds=2.5)
    assert c1 == 5

    # System load above max_cpu_load causes gentle step-down
    with patch.object(ctrl, "sample_system_load", return_value=8.5):
        c2 = ctrl.record_success(latency_seconds=0.1)
        assert c2 == 4


def test_adaptive_hooks_integration() -> None:
    policy = AdaptiveConcurrencyPolicy(
        min_concurrency=1,
        max_concurrency=10,
        initial_concurrency=3,
        step_increase=1,
    )
    ctrl = AdaptiveConcurrencyController(policy)
    hooks = ctrl.create_hooks()

    from orchestration_engine.builder import WorkflowBuilder

    dummy_task = WorkflowBuilder("wf").task("task_x", name="Task X").build().tasks[0]

    # Start task
    assert hooks.on_task_start is not None
    hooks.on_task_start(dummy_task)
    assert ctrl.stats()["active_tasks"] == 1

    # Task succeeds
    assert hooks.on_task_succeeded is not None
    hooks.on_task_succeeded(dummy_task)
    assert ctrl.stats()["active_tasks"] == 0
    assert ctrl.current_concurrency == 4

    # Task retry triggers backoff
    assert hooks.on_task_retry is not None
    hooks.on_task_retry(dummy_task)
    assert ctrl.current_concurrency == 2
