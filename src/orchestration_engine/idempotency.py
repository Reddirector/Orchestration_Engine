"""Distributed Idempotency and Exactly-Once Execution Semantics.

Guarantees that side-effecting operations (e.g. payment processing, order creation)
are executed at most once, even across worker retries, timeouts, and concurrent attempts.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeVar

from orchestration_engine.errors import OrchestrationError, PersistenceError
from orchestration_engine.persistence import get_connection

F = TypeVar("F", bound=Callable[..., Any])


class IdempotencyStatus(StrEnum):
    """Lifecycle state of an idempotency record."""

    PENDING = "pending"
    COMMITTED = "committed"
    ABORTED = "aborted"


class IdempotencyConflictError(OrchestrationError):
    """Raised when an operation with the same idempotency key is currently pending execution."""


@dataclass(frozen=True)
class IdempotencyRecord:
    """Persisted idempotency record."""

    key: str
    status: IdempotencyStatus
    output: Any | None
    error: str | None
    created_at: float
    updated_at: float
    expires_at: float | None


class IdempotencyStore:
    """SQLite-backed distributed idempotency store with three-phase commit semantics."""

    def __init__(
        self,
        db_path: str = "orchestration.db",
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = db_path
        self._conn = conn
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        return get_connection(self.db_path)

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency_records (
                        key TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        output_json TEXT,
                        error TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        expires_at REAL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_expires "
                    "ON idempotency_records(expires_at)"
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Failed to initialize idempotency schema: {exc}") from exc
        finally:
            if self._conn is None:
                conn.close()

    def get_record(self, key: str) -> IdempotencyRecord | None:
        """Fetch the current record for a key if it exists and has not expired."""
        now = time.time()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT key, status, output_json, error, created_at, updated_at, expires_at
                FROM idempotency_records WHERE key = ?
                """,
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            expires_at = float(row[6]) if row[6] is not None else None
            if expires_at is not None and expires_at < now:
                # Expired record
                return None

            output = json.loads(row[2]) if row[2] is not None else None
            return IdempotencyRecord(
                key=row[0],
                status=IdempotencyStatus(row[1]),
                output=output,
                error=row[3],
                created_at=float(row[4]),
                updated_at=float(row[5]),
                expires_at=expires_at,
            )
        finally:
            if self._conn is None:
                conn.close()

    def acquire(
        self,
        key: str,
        *,
        ttl_seconds: float | None = 3600.0,
    ) -> tuple[bool, IdempotencyRecord]:
        """Attempt to acquire a key for execution.

        Returns:
            (is_newly_acquired, record)
            - True: caller executes task and calls commit() or abort().
            - False with COMMITTED: caller uses cached output.
            - False with PENDING: another worker is executing.
        """
        now = time.time()
        expires_at = (now + ttl_seconds) if ttl_seconds is not None else None
        conn = self._get_conn()
        try:
            with conn:
                # Clean up expired row if present
                conn.execute(
                    "DELETE FROM idempotency_records WHERE key = ? AND expires_at < ?",
                    (key, now),
                )

                # Attempt insert
                try:
                    conn.execute(
                        """
                        INSERT INTO idempotency_records (
                            key, status, output_json, error, created_at, updated_at, expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            IdempotencyStatus.PENDING.value,
                            None,
                            None,
                            now,
                            now,
                            expires_at,
                        ),
                    )
                    return True, IdempotencyRecord(
                        key=key,
                        status=IdempotencyStatus.PENDING,
                        output=None,
                        error=None,
                        created_at=now,
                        updated_at=now,
                        expires_at=expires_at,
                    )
                except sqlite3.IntegrityError:
                    # Key already exists
                    pass

            # If insert failed, fetch existing record
            existing = self.get_record(key)
            if existing is None:
                # Expired right after collision, retry once recursively
                return self.acquire(key, ttl_seconds=ttl_seconds)
            return False, existing
        finally:
            if self._conn is None:
                conn.close()

    def commit(self, key: str, output: Any) -> None:
        """Mark an acquired key as COMMITTED with its serialized output."""
        now = time.time()
        out_json = json.dumps(output)
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE idempotency_records
                    SET status = ?, output_json = ?, updated_at = ?
                    WHERE key = ?
                    """,
                    (IdempotencyStatus.COMMITTED.value, out_json, now, key),
                )
        finally:
            if self._conn is None:
                conn.close()

    def abort(self, key: str, error: str | None = None) -> None:
        """Mark an acquired key as ABORTED (allowing future retries or recording error)."""
        now = time.time()
        conn = self._get_conn()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE idempotency_records
                    SET status = ?, error = ?, updated_at = ?
                    WHERE key = ?
                    """,
                    (IdempotencyStatus.ABORTED.value, error, now, key),
                )
        finally:
            if self._conn is None:
                conn.close()


def idempotent(
    store: IdempotencyStore,
    key_func: Callable[..., str],
    *,
    ttl_seconds: float | None = 3600.0,
) -> Callable[[F], F]:
    """Decorator to enforce exactly-once execution semantics on a function."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = key_func(*args, **kwargs)
            is_new, record = store.acquire(key, ttl_seconds=ttl_seconds)

            if not is_new:
                if record.status == IdempotencyStatus.COMMITTED:
                    return record.output
                if record.status == IdempotencyStatus.PENDING:
                    raise IdempotencyConflictError(
                        f"Operation with idempotency key '{key}' is currently pending execution"
                    )
                # If aborted, re-attempt
                store.abort(key)

            try:
                result = func(*args, **kwargs)
                store.commit(key, result)
                return result
            except BaseException as exc:
                store.abort(key, error=str(exc))
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
