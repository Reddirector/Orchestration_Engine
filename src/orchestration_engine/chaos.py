"""Chaos Engineering and Fault Injection.

Allows developers and SREs to test the resilience of workflows, sagas, circuit breakers,
and retries by deterministically injecting synthetic failures, network latency, and jitter.
"""

from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from orchestration_engine.errors import OrchestrationError

F = TypeVar("F", bound=Callable[..., Any])


class ChaosFaultError(OrchestrationError):
    """Raised when an operation is faulted by a ChaosPolicy."""


@dataclass
class ChaosPolicy:
    """Configuration policy governing chaos fault and latency injection."""

    failure_rate: float = 0.0
    exception_factory: Callable[[], Exception] | None = None
    latency_seconds: float = 0.0
    latency_jitter_seconds: float = 0.0
    task_targets: set[str] | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.failure_rate <= 1.0):
            raise ValueError(f"failure_rate must be between 0.0 and 1.0, got {self.failure_rate}")
        if self.latency_seconds < 0.0:
            raise ValueError("latency_seconds cannot be negative")
        if self.latency_jitter_seconds < 0.0:
            raise ValueError("latency_jitter_seconds cannot be negative")


class ChaosInjector:
    """Engine that applies a ChaosPolicy to function executions and task runners."""

    def __init__(self, policy: ChaosPolicy) -> None:
        self.policy = policy
        self._rng = random.Random(policy.seed) if policy.seed is not None else random.Random()

    def _matches_target(self, task_id: str | None) -> bool:
        if self.policy.task_targets is None:
            return True
        if task_id is None:
            return True
        return task_id in self.policy.task_targets

    def should_fault(self, task_id: str | None = None) -> bool:
        """Evaluate if an execution should trigger a fault."""
        if not self._matches_target(task_id):
            return False
        if self.policy.failure_rate <= 0.0:
            return False
        if self.policy.failure_rate >= 1.0:
            return True
        return self._rng.random() < self.policy.failure_rate

    def apply_latency(self, task_id: str | None = None) -> float:
        """Apply configured latency and jitter. Returns the actual slept duration."""
        if not self._matches_target(task_id):
            return 0.0

        base = self.policy.latency_seconds
        jitter = 0.0
        if self.policy.latency_jitter_seconds > 0.0:
            jitter = self._rng.uniform(0.0, self.policy.latency_jitter_seconds)

        total_sleep = base + jitter
        if total_sleep > 0.0:
            time.sleep(total_sleep)
        return total_sleep

    def wrap(self, func: F) -> F:
        """Wrap a callable to inject chaos latency and faults."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract task_id if first arg has task_id attribute (e.g. Task model) or kwarg
            task_id: str | None = None
            if args and hasattr(args[0], "task_id"):
                task_id = str(args[0].task_id)
            elif "task_id" in kwargs:
                task_id = str(kwargs["task_id"])

            self.apply_latency(task_id)

            if self.should_fault(task_id):
                if self.policy.exception_factory is not None:
                    raise self.policy.exception_factory()
                raise ChaosFaultError(f"Chaos injected fault on task '{task_id or 'anonymous'}'")

            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


def with_chaos(policy: ChaosPolicy) -> Callable[[F], F]:
    """Decorator to wrap a function with a ChaosPolicy."""
    injector = ChaosInjector(policy)

    def decorator(func: F) -> F:
        return injector.wrap(func)

    return decorator
