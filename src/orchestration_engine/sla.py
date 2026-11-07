"""Automated SLA Tracking, Business Deadlines, and Escalation Alerting.

Monitors task execution durations against Service Level Agreements (SLAs) distinct from
hard timeouts. Emits warnings at thresholds and executes escalation hooks upon deadline breaches.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class SLAPolicy:
    """Service Level Agreement policy for a task or workflow."""

    deadline_seconds: float
    warning_ratio: float = 0.8
    on_warning: Callable[[str, float, float], None] | None = None
    on_breach: Callable[[str, float, float], None] | None = None

    def __post_init__(self) -> None:
        if self.deadline_seconds <= 0.0:
            raise ValueError(f"deadline_seconds must be positive, got {self.deadline_seconds}")
        if not (0.0 < self.warning_ratio <= 1.0):
            raise ValueError(f"warning_ratio must be between 0.0 and 1.0, got {self.warning_ratio}")


@dataclass(frozen=True)
class SLABreachRecord:
    """Audit record capturing an SLA deadline breach."""

    task_id: str
    started_at: float
    deadline_seconds: float
    breached_at: float
    elapsed_seconds: float


class SLAMonitor:
    """Tracks active task execution times and detects warnings and breaches."""

    def __init__(self) -> None:
        self._policies: dict[str, SLAPolicy] = {}
        self._active_tasks: dict[str, float] = {}
        self._warned: set[str] = set()
        self._breached: dict[str, SLABreachRecord] = {}

    def register_sla(self, task_id: str, policy: SLAPolicy) -> None:
        """Register an SLA policy for a task."""
        self._policies[task_id] = policy

    def record_start(self, task_id: str, timestamp: float | None = None) -> None:
        """Record the start timestamp of a task execution."""
        start_time = timestamp if timestamp is not None else time.time()
        self._active_tasks[task_id] = start_time

    def record_completion(self, task_id: str, timestamp: float | None = None) -> float | None:
        """Record task completion and stop active SLA tracking."""
        start = self._active_tasks.pop(task_id, None)
        self._warned.discard(task_id)
        if start is None:
            return None
        end_time = timestamp if timestamp is not None else time.time()
        return max(0.0, end_time - start)

    def check_slas(self, now: float | None = None) -> list[SLABreachRecord]:
        """Check all active tasks against their registered SLA policies.

        Fires on_warning and on_breach callbacks appropriately.
        """
        current_time = now if now is not None else time.time()
        new_breaches: list[SLABreachRecord] = []

        for task_id, started_at in list(self._active_tasks.items()):
            policy = self._policies.get(task_id)
            if not policy:
                continue

            elapsed = max(0.0, current_time - started_at)
            warn_threshold = policy.deadline_seconds * policy.warning_ratio

            # Check warning
            if elapsed >= warn_threshold and task_id not in self._warned:
                self._warned.add(task_id)
                if policy.on_warning:
                    policy.on_warning(task_id, elapsed, policy.deadline_seconds)

            # Check breach
            if elapsed >= policy.deadline_seconds and task_id not in self._breached:
                record = SLABreachRecord(
                    task_id=task_id,
                    started_at=started_at,
                    deadline_seconds=policy.deadline_seconds,
                    breached_at=current_time,
                    elapsed_seconds=elapsed,
                )
                self._breached[task_id] = record
                new_breaches.append(record)
                if policy.on_breach:
                    policy.on_breach(task_id, elapsed, policy.deadline_seconds)

        return new_breaches

    def get_breaches(self) -> list[SLABreachRecord]:
        """Return all recorded SLA breaches."""
        return list(self._breached.values())
