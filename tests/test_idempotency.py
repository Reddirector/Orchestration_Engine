"""Tests for Distributed Idempotency and Exactly-Once Execution."""

from __future__ import annotations

import time
from typing import Any

import pytest

from orchestration_engine.idempotency import (
    IdempotencyConflictError,
    IdempotencyStatus,
    IdempotencyStore,
    idempotent,
)


def test_idempotency_store_lifecycle(tmp_path: Any) -> None:
    db = str(tmp_path / "idem.db")
    store = IdempotencyStore(db)

    # 1. Acquire key
    is_new, record = store.acquire("charge_req_101", ttl_seconds=60.0)
    assert is_new is True
    assert record.status == IdempotencyStatus.PENDING

    # 2. Concurrent acquire should return existing pending record
    is_new_2, record_2 = store.acquire("charge_req_101", ttl_seconds=60.0)
    assert is_new_2 is False
    assert record_2.status == IdempotencyStatus.PENDING

    # 3. Commit output
    store.commit("charge_req_101", {"tx_id": "tx_abc", "amount": 100})

    # 4. Subsequent acquire should return COMMITTED with output
    is_new_3, record_3 = store.acquire("charge_req_101", ttl_seconds=60.0)
    assert is_new_3 is False
    assert record_3.status == IdempotencyStatus.COMMITTED
    assert record_3.output == {"tx_id": "tx_abc", "amount": 100}


def test_idempotency_abort_and_retry(tmp_path: Any) -> None:
    db = str(tmp_path / "idem_abort.db")
    store = IdempotencyStore(db)

    is_new, _ = store.acquire("fail_key", ttl_seconds=60.0)
    assert is_new is True

    # Abort with error
    store.abort("fail_key", error="Network timeout")
    rec = store.get_record("fail_key")
    assert rec is not None
    assert rec.status == IdempotencyStatus.ABORTED
    assert rec.error == "Network timeout"


def test_idempotency_ttl_expiration(tmp_path: Any) -> None:
    db = str(tmp_path / "idem_ttl.db")
    store = IdempotencyStore(db)

    # Acquire with very short TTL
    is_new, _ = store.acquire("short_key", ttl_seconds=0.05)
    assert is_new is True
    store.commit("short_key", "result_1")

    # Wait for expiration
    time.sleep(0.06)
    assert store.get_record("short_key") is None

    # Re-acquire after expiration should succeed as new
    is_new_again, _ = store.acquire("short_key", ttl_seconds=60.0)
    assert is_new_again is True


def test_idempotent_decorator(tmp_path: Any) -> None:
    db = str(tmp_path / "idem_dec.db")
    store = IdempotencyStore(db)

    call_count = 0

    @idempotent(store, key_func=lambda req_id, amt: f"charge:{req_id}")
    def process_charge(req_id: str, amt: int) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {"req_id": req_id, "amount": amt, "status": "approved"}

    # First call: executes body
    res1 = process_charge("order-99", 500)
    assert call_count == 1
    assert res1["status"] == "approved"

    # Second call with same req_id: returns cached result without executing body
    res2 = process_charge("order-99", 500)
    assert call_count == 1
    assert res2 == res1

    # Different req_id: executes
    res3 = process_charge("order-100", 500)
    assert call_count == 2
    assert res3["req_id"] == "order-100"


def test_idempotent_decorator_conflict_and_exception(tmp_path: Any) -> None:
    db = str(tmp_path / "idem_err.db")
    store = IdempotencyStore(db)

    # Manually acquire key in PENDING state to simulate concurrent worker
    store.acquire("op:pending-123")

    @idempotent(store, key_func=lambda op_id: f"op:{op_id}")
    def execute_op(op_id: str) -> str:
        return "done"

    with pytest.raises(IdempotencyConflictError):
        execute_op("pending-123")
