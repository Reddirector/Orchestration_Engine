"""Tests for Chaos Engineering and Fault Injection."""

from __future__ import annotations

import time

import pytest

from orchestration_engine.chaos import (
    ChaosInjector,
    ChaosPolicy,
    with_chaos,
)


def test_chaos_policy_validation() -> None:
    with pytest.raises(ValueError):
        ChaosPolicy(failure_rate=1.5)
    with pytest.raises(ValueError):
        ChaosPolicy(failure_rate=-0.1)
    with pytest.raises(ValueError):
        ChaosPolicy(latency_seconds=-1.0)
    with pytest.raises(ValueError):
        ChaosPolicy(latency_jitter_seconds=-0.5)


def test_chaos_deterministic_failure_rate() -> None:
    # 100% failure rate
    policy_always = ChaosPolicy(failure_rate=1.0)
    injector_always = ChaosInjector(policy_always)
    assert injector_always.should_fault() is True

    # 0% failure rate
    policy_never = ChaosPolicy(failure_rate=0.0)
    injector_never = ChaosInjector(policy_never)
    assert injector_never.should_fault() is False

    # Seeded reproducibility
    policy_seeded = ChaosPolicy(failure_rate=0.5, seed=42)
    inj1 = ChaosInjector(policy_seeded)
    inj2 = ChaosInjector(policy_seeded)

    seq1 = [inj1.should_fault() for _ in range(20)]
    seq2 = [inj2.should_fault() for _ in range(20)]
    assert seq1 == seq2


def test_chaos_task_targeting() -> None:
    policy = ChaosPolicy(
        failure_rate=1.0,
        task_targets={"target_task"},
    )
    injector = ChaosInjector(policy)

    # Targeted task should fault
    assert injector.should_fault("target_task") is True
    # Non-targeted task should never fault
    assert injector.should_fault("other_task") is False


def test_chaos_wrapper_and_decorator() -> None:
    policy = ChaosPolicy(
        failure_rate=1.0,
        exception_factory=lambda: ConnectionResetError("Simulated socket drop"),
        task_targets={"flaky_step"},
    )

    @with_chaos(policy)
    def my_runner(task_id: str, x: int) -> int:
        return x * 2

    # Normal step passes
    assert my_runner(task_id="normal_step", x=5) == 10

    # Targeted step raises configured exception
    with pytest.raises(ConnectionResetError) as exc_info:
        my_runner(task_id="flaky_step", x=5)
    assert "Simulated socket drop" in str(exc_info.value)


def test_chaos_latency_injection() -> None:
    policy = ChaosPolicy(
        latency_seconds=0.05,
        latency_jitter_seconds=0.02,
        seed=123,
    )
    injector = ChaosInjector(policy)

    start = time.perf_counter()
    slept = injector.apply_latency("any_task")
    elapsed = time.perf_counter() - start

    assert slept >= 0.05
    assert elapsed >= 0.045
