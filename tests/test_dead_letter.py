"""Tests for Dead Letter Queue (DLQ)."""

from __future__ import annotations

import time
from typing import Any

from orchestration_engine.dead_letter import (
    DeadLetterQueue,
    create_dlq_hook,
)
from orchestration_engine.models import RetryPolicy, Task
from orchestration_engine.runner import run_workflow


def test_dlq_enqueue_get_list(tmp_path: Any) -> None:
    db = str(tmp_path / "dlq.db")
    dlq = DeadLetterQueue(db)

    msg_id = dlq.enqueue(
        workflow_id="wf-orders",
        run_id="run-1",
        task_id="payment",
        inputs={"amount": 99.5},
        error="Gateway timeout",
        stack_trace="Traceback: ...",
        attempt_count=3,
        metadata={"priority": "high"},
    )

    assert msg_id is not None
    msg = dlq.get_message(msg_id)
    assert msg is not None
    assert msg.workflow_id == "wf-orders"
    assert msg.task_id == "payment"
    assert msg.inputs == {"amount": 99.5}
    assert msg.error_message == "Gateway timeout"
    assert msg.attempt_count == 3
    assert msg.metadata == {"priority": "high"}

    # List
    messages = dlq.list_messages(workflow_id="wf-orders")
    assert len(messages) == 1
    assert messages[0].message_id == msg_id

    # Filter non-matching
    assert dlq.list_messages(workflow_id="other-wf") == []


def test_dlq_replay_and_auto_purge(tmp_path: Any) -> None:
    db = str(tmp_path / "dlq_replay.db")
    dlq = DeadLetterQueue(db)

    msg_id = dlq.enqueue(
        workflow_id="wf-calc",
        run_id="run-2",
        task_id="multiply",
        inputs={"a": 6, "b": 7},
        error="Temporary crash",
    )

    replayed_result: list[int] = []

    def fixer(a: int, b: int) -> int:
        res = a * b
        replayed_result.append(res)
        return res

    res = dlq.replay(msg_id, fixer)
    assert res == 42
    assert replayed_result == [42]

    # After successful replay, message is removed from DLQ
    assert dlq.get_message(msg_id) is None


def test_dlq_purge(tmp_path: Any) -> None:
    db = str(tmp_path / "dlq_purge.db")
    dlq = DeadLetterQueue(db)

    dlq.enqueue(workflow_id="wf-1", run_id="r1", task_id="t1", error="err1", timestamp=100.0)
    dlq.enqueue(workflow_id="wf-1", run_id="r2", task_id="t2", error="err2", timestamp=200.0)
    dlq.enqueue(workflow_id="wf-2", run_id="r3", task_id="t3", error="err3", timestamp=300.0)

    # Purge wf-1
    purged = dlq.purge(workflow_id="wf-1")
    assert purged == 2
    assert len(dlq.list_messages()) == 1


def test_create_dlq_hook_integration(tmp_path: Any) -> None:
    from orchestration_engine.builder import WorkflowBuilder

    db = str(tmp_path / "dlq_hook.db")
    dlq = DeadLetterQueue(db)

    wf = (
        WorkflowBuilder("hook-test-wf")
        .task("failing_task", retry_policy=RetryPolicy(1, 0.05))
        .build()
    )

    hook = create_dlq_hook(dlq, workflow_id="hook-test-wf", run_id="run-99")

    task_states: dict[str, Any] = {}

    def runner(task: Task) -> bool:
        if task.task_id == "failing_task":
            raise RuntimeError("FATAL ERROR")
        return True

    from orchestration_engine.persistence import get_connection

    conn = get_connection(db)
    run_workflow(
        wf,
        task_runner=runner,
        task_states=task_states,
        time_source=time.time,
        conn=conn,
        hooks=hook,
        run_id="run-99",
    )

    # Message should be in DLQ
    messages = dlq.list_messages(workflow_id="hook-test-wf")
    assert len(messages) == 1
    assert messages[0].task_id == "failing_task"
    assert "FATAL ERROR" in messages[0].error_message
