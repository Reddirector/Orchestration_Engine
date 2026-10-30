"""Sandboxing and Resource-Constrained Task Execution.

Prevents rogue tasks, memory leaks, or runaway algorithms from crashing the engine.
Applies hard POSIX resource limits (RAM memory bounding, CPU execution time, file descriptors)
in an isolated subprocess with automatic recovery on out-of-memory or timeout conditions.
"""

from __future__ import annotations

import collections.abc
import dataclasses
import functools
import multiprocessing
from typing import Any, TypeVar

F = TypeVar("F", bound=collections.abc.Callable[..., Any])


@dataclasses.dataclass(frozen=True)
class ResourceLimits:
    """Resource constraints applied to a sandboxed execution."""

    max_memory_mb: int | None = None
    max_cpu_seconds: int | None = None
    max_open_files: int | None = None


def _apply_limits(limits: ResourceLimits) -> None:
    """Apply resource constraints via POSIX setrlimit in child process."""
    try:
        import resource
    except ImportError:
        # Non-POSIX platform (e.g., Windows)
        return

    if limits.max_memory_mb is not None:
        bytes_limit = limits.max_memory_mb * 1024 * 1024
        # Limit address space
        if hasattr(resource, "RLIMIT_AS"):
            try:
                resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
            except (ValueError, OSError):
                pass
        elif hasattr(resource, "RLIMIT_DATA"):
            try:
                resource.setrlimit(resource.RLIMIT_DATA, (bytes_limit, bytes_limit))
            except (ValueError, OSError):
                pass

    if limits.max_cpu_seconds is not None:
        if hasattr(resource, "RLIMIT_CPU"):
            try:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (limits.max_cpu_seconds, limits.max_cpu_seconds + 1),
                )
            except (ValueError, OSError):
                pass

    if limits.max_open_files is not None:
        if hasattr(resource, "RLIMIT_NOFILE"):
            try:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE,
                    (limits.max_open_files, limits.max_open_files),
                )
            except (ValueError, OSError):
                pass


def _sandbox_target(
    func: collections.abc.Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    limits: ResourceLimits | None,
    pipe: Any,
) -> None:
    if limits:
        _apply_limits(limits)
    try:
        res = func(*args, **kwargs)
        pipe.send((True, res, None))
    except BaseException as exc:
        pipe.send((False, None, f"{type(exc).__name__}: {exc}"))


def sandboxed_run(
    func: collections.abc.Callable[..., Any],
    *args: Any,
    limits: ResourceLimits | None = None,
    timeout_seconds: float = 30.0,
    start_method: str | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a callable inside an isolated, resource-constrained subprocess.

    Raises:
        MemoryError: If the process exceeds max_memory_mb.
        TimeoutError: If the process exceeds timeout_seconds.
        RuntimeError: If the child process crashes or terminates abnormally.
    """
    if start_method is None:
        start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"

    ctx: Any = multiprocessing.get_context(start_method)
    parent_conn, child_conn = ctx.Pipe()

    proc = ctx.Process(
        target=_sandbox_target,
        args=(func, args, kwargs, limits, child_conn),
    )
    proc.start()
    child_conn.close()

    proc.join(timeout=timeout_seconds)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)
        raise TimeoutError(f"Sandboxed task exceeded timeout of {timeout_seconds}s")

    if parent_conn.poll():
        ok, res, err = parent_conn.recv()
        parent_conn.close()
        if not ok:
            if "MemoryError" in str(err):
                raise MemoryError(err)
            raise RuntimeError(err)
        return res

    parent_conn.close()
    if proc.exitcode != 0:
        # Exit code on SIGSEGV or OOM is typically negative or 137/139
        raise MemoryError(
            f"Sandboxed task terminated abruptly (exit code {proc.exitcode}); "
            f"likely exceeded resource limits"
        )
    raise RuntimeError("Sandboxed task produced no output")


def sandboxed(
    *,
    max_memory_mb: int | None = None,
    max_cpu_seconds: int | None = None,
    timeout_seconds: float = 30.0,
) -> collections.abc.Callable[[F], F]:
    """Decorator to enforce resource bounding on a function."""
    limits = ResourceLimits(
        max_memory_mb=max_memory_mb,
        max_cpu_seconds=max_cpu_seconds,
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return sandboxed_run(
                func,
                *args,
                limits=limits,
                timeout_seconds=timeout_seconds,
                **kwargs,
            )

        return wrapper  # type: ignore[return-value]

    return decorator
