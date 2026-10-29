"""Tests for Distributed Advisory Leasing and Mutual Exclusion Locks."""

from __future__ import annotations

from typing import Any

import pytest

from orchestration_engine.lease import (
    TaskLease,
    acquire_lease,
    get_lease,
    release_lease,
    renew_lease,
)


def test_lease_acquire_renew_release(tmp_path: Any) -> None:
    db = str(tmp_path / "lease.db")
    curr_time = 1000.0

    def mock_time() -> float:
        return curr_time

    # 1. Acquire lease
    ok = acquire_lease(db, "res-partition-1", "worker-a", ttl_seconds=30.0, time_source=mock_time)
    assert ok is True

    info = get_lease(db, "res-partition-1")
    assert info is not None
    assert info.owner_id == "worker-a"
    assert info.expires_at == 1030.0

    # 2. Worker B cannot acquire active lease
    ok_b = acquire_lease(
        db, "res-partition-1", "worker-b", ttl_seconds=30.0, time_source=mock_time
    )
    assert ok_b is False

    # 3. Renew lease
    curr_time = 1020.0
    renewed = renew_lease(
        db, "res-partition-1", "worker-a", ttl_seconds=30.0, time_source=mock_time
    )
    assert renewed is True
    info = get_lease(db, "res-partition-1")
    assert info is not None
    assert info.expires_at == 1050.0

    # 4. Release lease
    released = release_lease(db, "res-partition-1", "worker-a")
    assert released is True
    assert get_lease(db, "res-partition-1") is None


def test_lease_expiration_and_takeover(tmp_path: Any) -> None:
    db = str(tmp_path / "lease_exp.db")
    curr_time = 100.0

    def mock_time() -> float:
        return curr_time

    acquire_lease(db, "lock-x", "worker-1", ttl_seconds=10.0, time_source=mock_time)

    # Worker 2 tries before expiration -> fails
    curr_time = 105.0
    assert acquire_lease(db, "lock-x", "worker-2", ttl_seconds=10.0, time_source=mock_time) is False

    # Worker 2 tries after expiration -> succeeds
    curr_time = 111.0
    assert acquire_lease(db, "lock-x", "worker-2", ttl_seconds=10.0, time_source=mock_time) is True
    info = get_lease(db, "lock-x")
    assert info is not None
    assert info.owner_id == "worker-2"


def test_task_lease_context_manager(tmp_path: Any) -> None:
    db = str(tmp_path / "lease_cm.db")

    with TaskLease(db, "sync-resource", "agent-main", ttl_seconds=5.0, heartbeat_interval=0.5):
        info = get_lease(db, "sync-resource")
        assert info is not None
        assert info.owner_id == "agent-main"

        # Another worker fails to acquire
        with pytest.raises(TimeoutError):
            with TaskLease(db, "sync-resource", "agent-other", ttl_seconds=1.0):
                pass

    # Exited context manager -> lease released
    assert get_lease(db, "sync-resource") is None
