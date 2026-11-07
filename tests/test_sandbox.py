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


def _exploding_task() -> None:
    raise ValueError("exploded inside sandbox")


def test_sandboxed_run_runtime_error() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        sandboxed_run(_exploding_task, timeout_seconds=5.0)
    assert "ValueError: exploded inside sandbox" in str(exc_info.value)

    def _oom_task() -> None:
        raise MemoryError("simulated out of memory")

    with pytest.raises(MemoryError) as oom_info:
        sandboxed_run(_oom_task, timeout_seconds=5.0)
    assert "simulated out of memory" in str(oom_info.value)


def test_sandbox_helpers_coverage() -> None:
    from unittest.mock import patch

    from orchestration_engine.sandbox import _apply_limits, _sandbox_target

    # Always mock resource.setrlimit so the test runner's own limits are never altered
    with patch("resource.setrlimit") as mock_set:
        limits = ResourceLimits(max_memory_mb=128, max_cpu_seconds=5, max_open_files=256)
        _apply_limits(limits)
        assert mock_set.call_count >= 1

    # Test exception handling inside _apply_limits
    with patch("resource.setrlimit", side_effect=ValueError("bad limit")):
        limits = ResourceLimits(max_memory_mb=128, max_cpu_seconds=5, max_open_files=256)
        _apply_limits(limits)  # does not raise

    class DummyPipe:
        def __init__(self) -> None:
            self.data: list[tuple[bool, int | None, str | None]] = []

        def send(self, val: tuple[bool, int | None, str | None]) -> None:
            self.data.append(val)

    # Test success branch with limits (mocked setrlimit to protect test runner process)
    with patch("resource.setrlimit"):
        pipe = DummyPipe()
        limits = ResourceLimits(max_memory_mb=128)
        _sandbox_target(lambda x: x * 3, (10,), {}, limits, pipe)
        assert pipe.data == [(True, 30, None)]

    # Test failure branch
    pipe_fail = DummyPipe()
    _sandbox_target(_exploding_task, (), {}, None, pipe_fail)
    assert pipe_fail.data[0][0] is False
    assert "ValueError: exploded inside sandbox" in str(pipe_fail.data[0][2])
