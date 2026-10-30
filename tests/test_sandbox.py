"""Tests for Sandboxing and Resource-Constrained Task Execution."""

from __future__ import annotations

import time

import pytest

from orchestration_engine.sandbox import (
    ResourceLimits,
    sandboxed,
    sandboxed_run,
)


def _pure_add(a: int, b: int) -> int:
    return a + b


def _slow_task() -> None:
    time.sleep(2.0)


def _allocate_memory() -> int:
    # Attempt to allocate 250MB of data
    data = b"x" * (250 * 1024 * 1024)
    return len(data)


@sandboxed(timeout_seconds=5.0)
def _decorated_multiply(x: int, y: int) -> int:
    return x * y


def test_sandboxed_run_success() -> None:
    res = sandboxed_run(_pure_add, 10, 20)
    assert res == 30


def test_sandboxed_run_timeout() -> None:
    with pytest.raises(TimeoutError) as exc_info:
        sandboxed_run(_slow_task, timeout_seconds=0.2)
    assert "exceeded timeout" in str(exc_info.value)


def test_sandboxed_decorator() -> None:
    assert _decorated_multiply(6, 7) == 42


def test_sandboxed_memory_limit() -> None:
    # On Linux/POSIX, setting max_memory_mb=10 should prevent allocating 50MB
    try:
        import resource  # noqa: F401
    except ImportError:
        pytest.skip("resource module not available on this platform")

    limits = ResourceLimits(max_memory_mb=10)
    with pytest.raises((MemoryError, RuntimeError)):
        sandboxed_run(_allocate_memory, limits=limits, timeout_seconds=5.0)
