"""Tests for Resilient Circuit Breaker pattern."""

from __future__ import annotations

from typing import Any

import pytest

from orchestration_engine.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)


def _get_state(b: CircuitBreaker) -> str:
    return str(b.state.value)


def test_circuit_breaker_transitions_and_fast_fail() -> None:
    current_time = 1000.0

    def mock_time() -> float:
        return current_time

    breaker = CircuitBreaker(
        "api-payment",
        failure_threshold=2,
        recovery_timeout=10.0,
        success_threshold=2,
        time_source=mock_time,
    )

    assert _get_state(breaker) == CircuitState.CLOSED.value
    assert breaker.can_execute() is True

    # 1st failure
    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("Timeout")))
    assert _get_state(breaker) == CircuitState.CLOSED.value

    # 2nd failure -> Trips to OPEN
    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("Timeout 2")))
    assert _get_state(breaker) == CircuitState.OPEN.value
    assert breaker.can_execute() is False

    # Immediate next call fails fast without executing function
    executed = False

    def should_not_run() -> None:
        nonlocal executed
        executed = True

    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        breaker.call(should_not_run)

    assert executed is False
    assert exc_info.value.breaker_name == "api-payment"
    assert "Circuit 'api-payment' is OPEN" in str(exc_info.value)

    # Fast forward past recovery timeout -> transitions to HALF_OPEN
    current_time += 10.5
    assert _get_state(breaker) == CircuitState.HALF_OPEN.value
    assert breaker.can_execute() is True

    # 1st success in HALF_OPEN
    res = breaker.call(lambda: "success 1")
    assert res == "success 1"
    assert _get_state(breaker) == CircuitState.HALF_OPEN.value

    # 2nd success in HALF_OPEN -> resets to CLOSED
    res = breaker.call(lambda: "success 2")
    assert res == "success 2"
    assert _get_state(breaker) == CircuitState.CLOSED.value
    assert breaker.can_execute() is True


def test_circuit_breaker_half_open_failure_re_trips() -> None:
    current_time = 500.0

    def mock_time() -> float:
        return current_time

    breaker = CircuitBreaker(
        "flaky-service",
        failure_threshold=2,
        recovery_timeout=5.0,
        success_threshold=2,
        time_source=mock_time,
    )

    # Trip to OPEN
    breaker.record_failure()
    breaker.record_failure()
    assert _get_state(breaker) == CircuitState.OPEN.value

    # Advance to HALF_OPEN
    current_time += 6.0
    assert _get_state(breaker) == CircuitState.HALF_OPEN.value

    # A failure in HALF_OPEN immediately re-trips to OPEN
    with pytest.raises(RuntimeError):
        breaker.call(lambda: (_ for _ in ()).throw(RuntimeError("Still dead")))

    assert _get_state(breaker) == CircuitState.OPEN.value


def test_circuit_breaker_sqlite_persistence(tmp_path: Any) -> None:
    db = str(tmp_path / "cb.db")
    b1 = CircuitBreaker("shared-api", failure_threshold=2, recovery_timeout=20.0, db_path=db)
    b2 = CircuitBreaker("shared-api", failure_threshold=2, recovery_timeout=20.0, db_path=db)

    b1.record_failure()
    b1.record_failure()
    assert _get_state(b1) == CircuitState.OPEN.value

    # b2 reloads from db and sees OPEN
    b2._load_from_db()
    assert _get_state(b2) == CircuitState.OPEN.value

    # Reset
    b1.reset()
    assert _get_state(b1) == CircuitState.CLOSED.value
    b2._load_from_db()
    assert _get_state(b2) == CircuitState.CLOSED.value


def test_circuit_breaker_decorator() -> None:
    breaker = CircuitBreaker("decorator-cb", failure_threshold=1, recovery_timeout=5.0)

    @breaker.protect
    def compute(x: int) -> int:
        if x < 0:
            raise ValueError("Negative number")
        return x * 2

    assert compute(5) == 10

    with pytest.raises(ValueError):
        compute(-1)

    assert breaker.state == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        compute(5)
