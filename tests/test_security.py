"""Security and hardening tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.cli import _load_workflow_file
from orchestration_engine.errors import WorkflowDefinitionError, WorkflowValidationError
from orchestration_engine.loader import run_workflow_from_file
from orchestration_engine.models import RetryPolicy, Task, TaskState, Workflow
from orchestration_engine.persistence import get_connection, log_task_event
from orchestration_engine.validation import (
    MAX_DEPENDENCIES_PER_TASK,
    MAX_TASKS_PER_WORKFLOW,
    get_workflow_validation_error,
)


def test_workflow_task_count_limit() -> None:
    builder = WorkflowBuilder("wf-huge", "Huge Workflow")
    for i in range(MAX_TASKS_PER_WORKFLOW + 1):
        builder.task(f"t{i}", name=f"Task {i}")
    with pytest.raises(
        WorkflowValidationError, match=f"exceeds limit of {MAX_TASKS_PER_WORKFLOW}"
    ):
        builder.build()


def test_task_dependencies_count_limit() -> None:
    deps = [f"dep_{i}" for i in range(MAX_DEPENDENCIES_PER_TASK + 1)]
    task = Task(
        task_id="t1",
        workflow_id="wf-deps",
        name="Task 1",
        description="",
        dependencies=deps,
        state=TaskState.PENDING,
        retry_policy=RetryPolicy(3, 1.0),
    )
    wf = Workflow(
        workflow_id="wf-deps",
        name="Deps Workflow",
        description="",
        tasks=[task],
    )
    err = get_workflow_validation_error(wf)
    assert err is not None
    assert f"exceeds limit of {MAX_DEPENDENCIES_PER_TASK}" in err


def test_file_size_limit_json(tmp_path: Path) -> None:
    large_file = tmp_path / "large_workflow.json"
    # Create file slightly exceeding 10 MB with spaces
    large_file.write_bytes(b" " * (10 * 1024 * 1024 + 1))

    with pytest.raises(WorkflowDefinitionError, match="exceeds maximum"):
        run_workflow_from_file(
            str(large_file),
            lambda t: True,
            lambda: 0.0,
            get_connection(":memory:"),
        )

    with pytest.raises(WorkflowDefinitionError, match="exceeds maximum"):
        _load_workflow_file(str(large_file))


def test_sql_injection_safety() -> None:
    conn = get_connection(":memory:")
    malicious_task_id = "task'; DROP TABLE task_events; --"
    malicious_workflow_id = "wf'; DROP TABLE runs; --"

    # Insert malicious task event
    log_task_event(
        conn,
        workflow_id=malicious_workflow_id,
        task_id=malicious_task_id,
        old_state="pending",
        new_state="running",
        timestamp=100.0,
        attempt_count=1,
    )

    # Verify tables still exist and malicious payload is stored literally
    cur = conn.execute("SELECT count(*) FROM task_events WHERE task_id = ?", (malicious_task_id,))
    assert cur.fetchone()[0] == 1

    cur = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'task_events'"
    )
    assert cur.fetchone()[0] == 1


def test_yaml_safe_load_blocks_arbitrary_code(tmp_path: Path) -> None:
    try:
        from orchestration_engine.loader import load_workflow_from_yaml
    except ImportError:
        pytest.skip("PyYAML extra not installed")

    unsafe_yaml = tmp_path / "unsafe.yaml"
    unsafe_yaml.write_text(
        """
workflow_id: test
name: !!python/object/apply:os.system ["echo pwned"]
tasks: []
"""
    )
    with pytest.raises((yaml.constructor.ConstructorError, WorkflowDefinitionError)):
        load_workflow_from_yaml(str(unsafe_yaml))
