import sqlite3
import threading
import time
from pathlib import Path

import pytest

from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.models import (
    RetryPolicy,
    Task,
    TaskState,
    Workflow,
)
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow


def test_g1_default_timeout_thirty_seconds() -> None:
    task = Task("t1", "wf1", "name", "desc", [], TaskState.PENDING, RetryPolicy(1, 1))
    assert task.timeout_seconds == 30.0

    loaded = load_workflow_from_json({
        "workflow_id": "wf",
        "name": "n",
        "description": "d",
        "tasks": [{
            "task_id": "t1", "name": "n", "description": "d",
            "dependencies": [], "retry_policy": {"max_attempts": 1, "delay_seconds": 1}
        }]
    })
    assert loaded.tasks[0].timeout_seconds == 30.0

    loaded_null = load_workflow_from_json({
        "workflow_id": "wf",
        "name": "n",
        "description": "d",
        "tasks": [{
            "task_id": "t1", "name": "n", "description": "d",
            "dependencies": [], "retry_policy": {"max_attempts": 1, "delay_seconds": 1},
            "timeout_seconds": None,
        }]
    })
    assert loaded_null.tasks[0].timeout_seconds is None

    loaded_prec = load_workflow_from_json({
        "workflow_id": "wf",
        "name": "n",
        "description": "d",
        "default_timeout_seconds": 45.0,
        "tasks": [
            {
                "task_id": "t1", "name": "n", "description": "d",
                "dependencies": [], "retry_policy": {"max_attempts": 1, "delay_seconds": 1},
                "timeout_seconds": 10.0,
            },
            {
                "task_id": "t2", "name": "n", "description": "d",
                "dependencies": [], "retry_policy": {"max_attempts": 1, "delay_seconds": 1},
            }
        ]
    })
    assert loaded_prec.tasks[0].timeout_seconds == 10.0
    assert loaded_prec.tasks[1].timeout_seconds == 45.0


def test_g2_get_connection_accepts_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_db = tmp_path / "custom.db"
    conn = get_connection(custom_db)
    try:
        assert custom_db.exists()
    finally:
        conn.close()

    # Precedence test: env var
    env_db = tmp_path / "env.db"
    monkeypatch.setenv("ORCHESTRATION_ENGINE_DB", str(env_db))
    conn_env = get_connection()
    try:
        assert env_db.exists()
    finally:
        conn_env.close()

    # Explicit arg overrides env var
    override_db = tmp_path / "override.db"
    conn_override = get_connection(override_db)
    try:
        assert override_db.exists()
    finally:
        conn_override.close()

    # Memory db
    conn_mem = get_connection(":memory:")
    try:
        cursor = conn_mem.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
    finally:
        conn_mem.close()


def test_g3_timeout_does_not_block_engine(conn: sqlite3.Connection) -> None:
    unblock_event = threading.Event()
    task = Task(
        task_id="t1",
        workflow_id="wf1",
        name="Hung Task",
        description="desc",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(1, 1),
        timeout_seconds=0.1,
    )
    workflow = Workflow("wf1", "wf", "desc", [task])

    def blocking_runner(_t: Task) -> bool:
        unblock_event.wait(timeout=5.0)
        return True

    start = time.perf_counter()
    try:
        run_workflow(
            workflow,
            {},
            time_source=lambda: 100.0,
            task_runner=blocking_runner,
            conn=conn,
        )
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        assert task.state == TaskState.FAILED
    finally:
        unblock_event.set()


def test_g4_exceptions_retried_and_task_states_updated(conn: sqlite3.Connection) -> None:
    current_time = 100.0
    task = Task(
        task_id="t1",
        workflow_id="wf1",
        name="Flaky Task",
        description="desc",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(2, 5),
    )
    workflow = Workflow("wf1", "wf", "desc", [task])
    task_states: dict[str, TaskState] = {}
    attempts = 0

    def crashing_runner(_t: Task) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return True

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        current_time += seconds

    run_workflow(
        workflow,
        task_states,
        time_source=lambda: current_time,
        task_runner=crashing_runner,
        conn=conn,
        sleep=fake_sleep,
    )
    assert task.attempt_count == 2
    assert task.state == TaskState.SUCCEEDED
    assert task_states["t1"] == TaskState.SUCCEEDED
    assert task.last_error == "RuntimeError: boom"


@pytest.mark.xfail(strict=True, reason="G11")
def test_g11_float_seconds_and_validation() -> None:
    from orchestration_engine.validation import validate_workflow

    policy = RetryPolicy(max_attempts=0, delay_seconds=-1.0)  # type: ignore[arg-type]
    task = Task(
        "t1", "wf1", "name", "desc", [], TaskState.PENDING, policy, timeout_seconds=-5.0
    )
    wf = Workflow("wf1", "wf", "desc", [task])
    assert validate_workflow(wf) is False


@pytest.mark.xfail(strict=True, reason="G12")
def test_g12_orchestration_error_hierarchy() -> None:
    from orchestration_engine.errors import (  # type: ignore[import-not-found]
        OrchestrationError,
        WorkflowDefinitionError,
        WorkflowValidationError,
    )

    assert issubclass(WorkflowDefinitionError, OrchestrationError)
    assert issubclass(WorkflowDefinitionError, ValueError)
    assert issubclass(WorkflowValidationError, OrchestrationError)
    assert issubclass(WorkflowValidationError, ValueError)


def test_g13_retry_delay_measured_from_finish_time(conn: sqlite3.Connection) -> None:
    current_time = 100.0
    task = Task(
        task_id="t1",
        workflow_id="wf1",
        name="Long Failing Task",
        description="desc",
        dependencies=[],
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(2, 5),
    )
    workflow = Workflow("wf1", "wf", "desc", [task])

    def advancing_time() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        current_time += seconds

    def runner(_t: Task) -> bool:
        nonlocal current_time
        current_time += 20.0
        return False

    run_workflow(
        workflow,
        {},
        time_source=advancing_time,
        task_runner=runner,
        conn=conn,
        sleep=fake_sleep,
    )
    # Task ran attempt 1 (took 20s: 100 -> 120), failed, next_retry_at was set to 125.
    # Sleep advanced time to 125, attempt 2 ran (took 20s: 125 -> 145),
    # reached max_attempts (2) -> FAILED.
    assert task.attempt_count == 2
    assert task.state == TaskState.FAILED
    assert task.next_retry_at == 125.0
