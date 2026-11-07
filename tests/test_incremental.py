"""Tests for Incremental DAG Evaluation and Content-Addressable Execution."""

from __future__ import annotations

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.incremental import (
    IncrementalStore,
    compute_task_hash,
    wrap_incremental,
)
from orchestration_engine.models import Task, TaskResult, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_run_status


def test_compute_task_hash_stability() -> None:
    task_a = (
        WorkflowBuilder("wf")
        .task("task_a", name="A")
        .build()
        .tasks[0]
    )
    task_a.inputs["query"] = "SELECT * FROM users"

    h1 = compute_task_hash(task_a, code_fingerprint="v1.0")
    h2 = compute_task_hash(task_a, code_fingerprint="v1.0")
    assert h1 == h2
    assert len(h1) == 16

    # Changing code fingerprint changes hash
    h3 = compute_task_hash(task_a, code_fingerprint="v1.1")
    assert h1 != h3

    # Changing inputs changes hash
    task_a.inputs["query"] = "SELECT * FROM products"
    h4 = compute_task_hash(task_a, code_fingerprint="v1.0")
    assert h1 != h4


def test_incremental_store_crud() -> None:
    conn = get_connection(":memory:")
    store = IncrementalStore(conn)

    assert store.has("hash_123") is False
    assert store.get("hash_123") is None

    store.put("hash_123", "extract_data", {"rows": 100})
    assert store.has("hash_123") is True
    assert store.get("hash_123") == {"rows": 100}

    # Invalidate by task_id
    deleted = store.invalidate("extract_data")
    assert deleted == 1
    assert store.has("hash_123") is False


def test_wrap_incremental_skips_unchanged_tasks() -> None:
    conn = get_connection(":memory:")
    store = IncrementalStore(conn)

    call_count = {"step_1": 0, "step_2": 0}

    def real_runner(task: Task) -> TaskResult:
        call_count[task.task_id] += 1
        return TaskResult(ok=True, output=f"result_{task.task_id}")

    wrapped_runner, get_summary = wrap_incremental(
        store=store,
        runner=real_runner,
        code_fingerprints={"step_1": "hash_code_1", "step_2": "hash_code_2"},
    )

    wf = (
        WorkflowBuilder("incremental_wf")
        .task("step_1", name="Step 1")
        .task("step_2", name="Step 2", dependencies=["step_1"])
        .build()
    )

    # 1. First run: both tasks execute
    run_1 = run_workflow(
        workflow=wf,
        task_states={t.task_id: t.state for t in wf.tasks},
        time_source=lambda: 1000.0,
        task_runner=wrapped_runner,
        conn=conn,
        executor="_inline",
    )
    assert get_run_status(conn, run_1) == WorkflowStatus.SUCCEEDED
    assert call_count == {"step_1": 1, "step_2": 1}

    summary1 = get_summary()
    assert summary1.executed_task_ids == ["step_1", "step_2"]
    assert summary1.skipped_task_ids == []

    # 2. Second run with fresh task instances but same inputs & fingerprints:
    # Both tasks should be skipped from cache
    wf_2 = (
        WorkflowBuilder("incremental_wf")
        .task("step_1", name="Step 1")
        .task("step_2", name="Step 2", dependencies=["step_1"])
        .build()
    )

    wrapped_runner_2, get_summary_2 = wrap_incremental(
        store=store,
        runner=real_runner,
        code_fingerprints={"step_1": "hash_code_1", "step_2": "hash_code_2"},
    )

    run_2 = run_workflow(
        workflow=wf_2,
        task_states={t.task_id: t.state for t in wf_2.tasks},
        time_source=lambda: 1010.0,
        task_runner=wrapped_runner_2,
        conn=conn,
        executor="_inline",
    )
    assert get_run_status(conn, run_2) == WorkflowStatus.SUCCEEDED
    # Real runner calls should remain 1!
    assert call_count == {"step_1": 1, "step_2": 1}

    summary2 = get_summary_2()
    assert summary2.skipped_task_ids == ["step_1", "step_2"]
    assert summary2.executed_task_ids == []
