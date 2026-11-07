"""Adaptive Concurrency Control and Backpressure Feedback Loops.

Dynamically auto-tunes workflow worker concurrency using AIMD
(Additive Increase / Multiplicative Decrease) based on task execution latency,
transient error spikes, and system CPU load.
"""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from typing import Any

from orchestration_engine.models import Hooks, Task


@dataclasses.dataclass(frozen=True)
class AdaptiveConcurrencyPolicy:
    """Configuration governing adaptive concurrency scaling and backpressure."""

    min_concurrency: int = 1
    max_concurrency: int = 50
    initial_concurrency: int = 5
    backoff_factor: float = 0.5
    step_increase: int = 1
    latency_threshold_seconds: float = 2.0
    max_cpu_load: float | None = None


class AdaptiveConcurrencyController:
    """Thread-safe controller that dynamically adjusts worker concurrency."""

    def __init__(self, policy: AdaptiveConcurrencyPolicy | None = None) -> None:
        self.policy = policy or AdaptiveConcurrencyPolicy()
        self._current = self.policy.initial_concurrency
        self._lock = threading.Lock()
        self._task_start_times: dict[str, float] = {}
        self._active_count = 0

    @property
    def current_concurrency(self) -> int:
        """Current allowed concurrency level."""
        with self._lock:
            return self._current

    def sample_system_load(self) -> float | None:
        """Return 1-minute system load average on POSIX platforms, else None."""
        if hasattr(os, "getloadavg"):
            try:
                return os.getloadavg()[0]
            except OSError:
                return None
        return None

    def record_success(self, latency_seconds: float) -> int:
        """Record a successful task execution.

        Increases concurrency additively if latency is below threshold and
        system load is healthy; decreases if threshold exceeded.
        """
        with self._lock:
            load = self.sample_system_load()
            over_load = (
                self.policy.max_cpu_load is not None
                and load is not None
                and load > self.policy.max_cpu_load
            )
            over_latency = latency_seconds > self.policy.latency_threshold_seconds

            if over_latency or over_load:
                # Moderate backpressure: step down slightly
                self._current = max(
                    self.policy.min_concurrency,
                    self._current - self.policy.step_increase,
                )
            else:
                # Additive Increase
                self._current = min(
                    self.policy.max_concurrency,
                    self._current + self.policy.step_increase,
                )
            return self._current

    def record_failure(self, is_transient: bool = True) -> int:
        """Record a task failure.

        Multiplicatively decreases concurrency to relieve downstream pressure.
        """
        with self._lock:
            if is_transient:
                new_val = int(self._current * self.policy.backoff_factor)
                self._current = max(self.policy.min_concurrency, new_val)
            return self._current

    def create_hooks(self) -> Hooks:
        """Create non-blocking workflow Hooks that automatically feed latency and errors.

        into this adaptive controller.
        """

        def on_start(task: Task) -> None:
            with self._lock:
                self._task_start_times[task.task_id] = time.time()
                self._active_count += 1

        def on_succeeded(task: Task) -> None:
            now = time.time()
            start = self._task_start_times.pop(task.task_id, now)
            latency = max(0.0, now - start)
            self.record_success(latency)
            with self._lock:
                self._active_count = max(0, self._active_count - 1)

        def on_failed(task: Task) -> None:
            self._task_start_times.pop(task.task_id, None)
            self.record_failure(is_transient=True)
            with self._lock:
                self._active_count = max(0, self._active_count - 1)

        def on_retry(task: Task) -> None:
            self.record_failure(is_transient=True)

        return Hooks(
            on_task_start=on_start,
            on_task_succeeded=on_succeeded,
            on_task_failed=on_failed,
            on_task_retry=on_retry,
        )

    def stats(self) -> dict[str, Any]:
        """Diagnostic state dictionary."""
        with self._lock:
            return {
                "current_concurrency": self._current,
                "active_tasks": self._active_count,
                "system_load_1m": self.sample_system_load(),
                "policy": dataclasses.asdict(self.policy),
            }
