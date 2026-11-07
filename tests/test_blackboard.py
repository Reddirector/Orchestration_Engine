"""Tests for Shared Run-Scoped Blackboard Memory."""

from __future__ import annotations

from typing import Any

from orchestration_engine.blackboard import WorkflowBlackboard


def test_blackboard_crud_and_atomic_cas(tmp_path: Any) -> None:
    db = str(tmp_path / "blackboard.db")
    bb = WorkflowBlackboard("run-101", db)

    # 1. Initial get is default
    assert bb.get("missing_key", "default_val") == "default_val"
    assert bb.get_with_version("missing_key") is None

    # 2. Compare-and-swap when key does not exist (expected_version=0)
    assert bb.compare_and_swap("status", expected_version=0, new_value="INITIAL") is True
    val, ver = bb.get_with_version("status")  # type: ignore[misc]
    assert val == "INITIAL"
    assert ver == 1

    # 3. Conflict CAS with wrong version returns False
    assert bb.compare_and_swap("status", expected_version=99, new_value="SHOULD_FAIL") is False
    assert bb.get("status") == "INITIAL"

    # 4. Correct CAS with version=1 succeeds and increments version to 2
    assert bb.compare_and_swap("status", expected_version=1, new_value="PROCESSED") is True
    val2, ver2 = bb.get_with_version("status")  # type: ignore[misc]
    assert val2 == "PROCESSED"
    assert ver2 == 2


def test_blackboard_atomic_counter_and_dump(tmp_path: Any) -> None:
    db = str(tmp_path / "bb_counter.db")
    bb = WorkflowBlackboard("run-agent", db)

    # Increment counter
    c1 = bb.increment("tokens_used", delta=100)
    assert c1 == 100
    c2 = bb.increment("tokens_used", delta=50)
    assert c2 == 150

    # Set structured object
    bb.set("agent_plan", {"steps": ["step1", "step2"], "ready": True})

    keys = bb.list_keys()
    assert keys == ["agent_plan", "tokens_used"]

    dump = bb.dump_state()
    assert dump["tokens_used"] == 150
    assert dump["agent_plan"]["ready"] is True

    # Delete
    assert bb.delete("tokens_used") is True
    assert bb.delete("nonexistent") is False
    assert bb.list_keys() == ["agent_plan"]
