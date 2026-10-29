"""Distributed Advisory Leasing and Mutual Exclusion Locks.

Provides atomic distributed mutual exclusion across worker processes and nodes
using SQLite WAL mode without requiring external services like Redis or ZooKeeper.
Ensures only one worker executes a partitioned workflow step, scheduled batch, or
critical resource at any given moment.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import threading
import time
from collections.abc import Callable
from types import TracebackType

from orchestration_engine.persistence import get_connection


@dataclasses.dataclass(frozen=True)
class LeaseInfo:
    """Active lease status and ownership information."""

    resource_id: str
    owner_id: str
    acquired_at: float
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def _init_lease_tables(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_leases (
                resource_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )


def acquire_lease(
    db_path: str,
    resource_id: str,
    owner_id: str,
    *,
    ttl_seconds: float = 30.0,
    time_source: Callable[[], float] = time.time,
) -> bool:
    """Atomically attempt to acquire an advisory lease on a resource.

    Returns True if the lease was acquired or already owned by owner_id;
    False if held by another active owner.
    """
    now = time_source()
    expires_at = now + ttl_seconds
    conn = get_connection(db_path)
    _init_lease_tables(conn)

    with conn:
        # Check current lease
        cursor = conn.execute(
            "SELECT owner_id, expires_at FROM resource_leases WHERE resource_id = ?",
            (resource_id,),
        )
        row = cursor.fetchone()

        if row is None:
            # Not held by anyone -> insert
            try:
                conn.execute(
                    """
                    INSERT INTO resource_leases (resource_id, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (resource_id, owner_id, now, expires_at),
                )
                return True
            except sqlite3.IntegrityError:
                return False

        current_owner, current_expires = row[0], row[1]
        # Re-acquire if already owned or expired
        if current_owner == owner_id or now >= current_expires:
            cursor = conn.execute(
                """
                UPDATE resource_leases
                SET owner_id = ?, acquired_at = ?, expires_at = ?
                WHERE resource_id = ? AND (owner_id = ? OR expires_at <= ?)
                """,
                (owner_id, now, expires_at, resource_id, current_owner, now),
            )
            return cursor.rowcount > 0

        return False


def renew_lease(
    db_path: str,
    resource_id: str,
    owner_id: str,
    *,
    ttl_seconds: float = 30.0,
    time_source: Callable[[], float] = time.time,
) -> bool:
    """Extend the expiration time of an existing lease owned by owner_id."""
    now = time_source()
    expires_at = now + ttl_seconds
    conn = get_connection(db_path)
    _init_lease_tables(conn)

    with conn:
        cursor = conn.execute(
            """
            UPDATE resource_leases
            SET expires_at = ?
            WHERE resource_id = ? AND owner_id = ? AND expires_at > ?
            """,
            (expires_at, resource_id, owner_id, now),
        )
        return cursor.rowcount > 0


def release_lease(
    db_path: str,
    resource_id: str,
    owner_id: str,
) -> bool:
    """Atomically release an advisory lease."""
    conn = get_connection(db_path)
    _init_lease_tables(conn)

    with conn:
        cursor = conn.execute(
            "DELETE FROM resource_leases WHERE resource_id = ? AND owner_id = ?",
            (resource_id, owner_id),
        )
        return cursor.rowcount > 0


def get_lease(db_path: str, resource_id: str) -> LeaseInfo | None:
    """Retrieve lease metadata for a resource."""
    conn = get_connection(db_path)
    _init_lease_tables(conn)

    with conn:
        cursor = conn.execute(
            "SELECT resource_id, owner_id, acquired_at, expires_at "
            "FROM resource_leases WHERE resource_id = ?",
            (resource_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LeaseInfo(
            resource_id=row[0],
            owner_id=row[1],
            acquired_at=row[2],
            expires_at=row[3],
        )


class TaskLease:
    """Context manager for distributed mutual exclusion with automatic heartbeat renewal."""

    def __init__(
        self,
        db_path: str,
        resource_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 30.0,
        heartbeat_interval: float | None = None,
    ) -> None:
        self.db_path = db_path
        self.resource_id = resource_id
        self.owner_id = owner_id
        self.ttl_seconds = ttl_seconds
        self.heartbeat_interval = heartbeat_interval or (ttl_seconds / 3.0)
        self._stop_event = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._acquired = False

    def __enter__(self) -> TaskLease:
        acquired = acquire_lease(
            self.db_path,
            self.resource_id,
            self.owner_id,
            ttl_seconds=self.ttl_seconds,
        )
        if not acquired:
            raise TimeoutError(
                f"Could not acquire lease for resource '{self.resource_id}' "
                f"(held by another active worker)"
            )
        self._acquired = True

        # Start heartbeat thread
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        return self

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_interval):
            renewed = renew_lease(
                self.db_path,
                self.resource_id,
                self.owner_id,
                ttl_seconds=self.ttl_seconds,
            )
            if not renewed:
                break

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)
        if self._acquired:
            release_lease(self.db_path, self.resource_id, self.owner_id)
