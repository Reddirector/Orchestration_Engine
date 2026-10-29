"""Resilient Circuit Breaker pattern for external APIs and microservices.

Protects workflows from cascading failures when downstream services (e.g. OpenAI,
Stripe, external databases, cloud services) experience outages or rate limits.
When failures exceed a threshold, the breaker trips to OPEN, fast-failing subsequent
calls immediately without wasting threads or network timeouts.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any, TypeVar

from orchestration_engine.errors import OrchestrationError
from orchestration_engine.persistence import get_connection

F = TypeVar("F", bound=Callable[..., Any])


class CircuitState(StrEnum):
    """Current state of a CircuitBreaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(OrchestrationError):
    """Raised when an operation is attempted while the circuit is OPEN."""

    def __init__(self, breaker_name: str, recovery_time_remaining: float) -> None:
        self.breaker_name = breaker_name
        self.recovery_time_remaining = max(0.0, recovery_time_remaining)
        super().__init__(
            f"Circuit '{breaker_name}' is OPEN. Fast-failing execution. "
            f"Recovery trial in {self.recovery_time_remaining:.2f}s."
        )


class CircuitBreaker:
    """Thread-safe and optionally SQLite-persisted Circuit Breaker.

    Attributes:
        name: Unique identifier for the circuit.
        failure_threshold: Number of consecutive failures to trip from CLOSED to OPEN.
        recovery_timeout: Seconds to remain OPEN before attempting a trial in HALF_OPEN.
        success_threshold: Consecutive successful calls in HALF_OPEN to reset to CLOSED.
        db_path: Optional SQLite database path to synchronize state across processes.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
        db_path: str | None = None,
        time_source: Callable[[], float] = time.time,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be positive")
        if success_threshold <= 0:
            raise ValueError("success_threshold must be positive")

        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.db_path = db_path
        self._time_source = time_source
        self._lock = threading.Lock()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_state_change = self._time_source()
        self._last_failure_time = 0.0

        if self.db_path:
            self._init_db()
            self._load_from_db()

    def _init_db(self) -> None:
        assert self.db_path is not None
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_breakers (
                    name TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failure_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    last_state_change REAL NOT NULL,
                    last_failure_time REAL NOT NULL
                )
                """
            )

    def _load_from_db(self) -> None:
        if not self.db_path:
            return
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.execute(
                "SELECT state, failure_count, success_count, last_state_change, last_failure_time "
                "FROM circuit_breakers WHERE name = ?",
                (self.name,),
            )
            row = cursor.fetchone()
            if row:
                self._state = CircuitState(row[0])
                self._failure_count = row[1]
                self._success_count = row[2]
                self._last_state_change = row[3]
                self._last_failure_time = row[4]

    def _sync_to_db(self) -> None:
        if not self.db_path:
            return
        conn = get_connection(self.db_path)
        with conn:
            conn.execute(
                """
                INSERT INTO circuit_breakers (
                    name, state, failure_count, success_count,
                    last_state_change, last_failure_time
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    state = excluded.state,
                    failure_count = excluded.failure_count,
                    success_count = excluded.success_count,
                    last_state_change = excluded.last_state_change,
                    last_failure_time = excluded.last_failure_time
                """,
                (
                    self.name,
                    self._state.value,
                    self._failure_count,
                    self._success_count,
                    self._last_state_change,
                    self._last_failure_time,
                ),
            )

    @property
    def state(self) -> CircuitState:
        """Current state with time-based OPEN -> HALF_OPEN promotion."""
        with self._lock:
            self._check_half_open_transition()
            return self._state

    def _check_half_open_transition(self) -> None:
        if self._state == CircuitState.OPEN:
            now = self._time_source()
            if now - self._last_state_change >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._last_state_change = now
                self._sync_to_db()

    def can_execute(self) -> bool:
        """Return True if an execution attempt is allowed under current state."""
        with self._lock:
            self._check_half_open_transition()
            return self._state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful execution."""
        with self._lock:
            now = self._time_source()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_state_change = now
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0
            self._sync_to_db()

    def record_failure(self) -> None:
        """Record an execution failure, potentially tripping the circuit."""
        with self._lock:
            now = self._time_source()
            self._last_failure_time = now
            if self._state == CircuitState.HALF_OPEN:
                # Immediate trip back to OPEN
                self._state = CircuitState.OPEN
                self._last_state_change = now
                self._failure_count = self.failure_threshold
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._last_state_change = now
            self._sync_to_db()

    def reset(self) -> None:
        """Force reset the breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_state_change = self._time_source()
            self._sync_to_db()

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute callable within the circuit breaker guard."""
        with self._lock:
            self._check_half_open_transition()
            if self._state == CircuitState.OPEN:
                now = self._time_source()
                remaining = self.recovery_timeout - (now - self._last_state_change)
                raise CircuitBreakerOpenError(self.name, remaining)

        try:
            res = func(*args, **kwargs)
            self.record_success()
            return res
        except Exception:
            self.record_failure()
            raise

    def protect(self, func: F) -> F:
        """Decorator to guard a function with this circuit breaker."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)

        return wrapper  # type: ignore[return-value]
