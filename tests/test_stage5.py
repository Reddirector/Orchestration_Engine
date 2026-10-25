import sqlite3
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from orchestration_engine.models import (
    RetryPolicy,
    Task,
    TaskResult,
    TaskState,
    Workflow,
    WorkflowStatus,
)
from orchestration_engine.persistence import _migrate_database
from orchestration_engine.runner import resume_run, run_workflow


def test_task_result_frozen() -> None:
    res = TaskResult(ok=True, output={"key": "val"}, error=None)
    assert res.ok is True
    assert res.output == {"key": "val"}
    assert res.error is None

    with pytest.raises(FrozenInstanceError):
        res.ok = False  # type: ignore[misc]


def test_task_inputs_field_default() -> None:
    task = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    assert task.inputs == {}

    task_custom = Task(
        "t2", "wf", "T2", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0), inputs={"dep": 42}
    )
    assert task_custom.inputs == {"dep": 42}


def test_schema_v2_migration(conn: sqlite3.Connection) -> None:
    _migrate_database(conn)
    cur = conn.execute("PRAGMA user_version")
    assert cur.fetchone()[0] == 2

    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='task_outputs'"
    )
    assert cur.fetchone() is not None


def test_data_flow_pipeline_a_b_to_c(conn: sqlite3.Connection) -> None:
    tA = Task("tA", "wf", "A", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    tB = Task("tB", "wf", "B", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    tC = Task("tC", "wf", "C", "d", ["tA", "tB"], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [tA, tB, tC])

    c_inputs: dict[str, Any] = {}

    def runner(task: Task) -> Any:
        if task.task_id == "tA":
            return TaskResult(ok=True, output=10)
        elif task.task_id == "tB":
            return TaskResult(ok=True, output=20)
        elif task.task_id == "tC":
            nonlocal c_inputs
            c_inputs = dict(task.inputs)
            total = task.inputs["tA"] + task.inputs["tB"]
            return TaskResult(ok=True, output=total)
        return True

    run_id = run_workflow(wf, {}, time.time, runner, conn)
    assert tA.state == TaskState.SUCCEEDED
    assert tB.state == TaskState.SUCCEEDED
    assert tC.state == TaskState.SUCCEEDED
    assert c_inputs == {"tA": 10, "tB": 20}

    # Verify persisted outputs in database
    cur = conn.execute(
        "SELECT task_id, output_json FROM task_outputs WHERE run_id = ? ORDER BY task_id ASC",
        (run_id,),
    )
    rows = cur.fetchall()
    assert len(rows) == 3
    assert rows[0] == ("tA", "10")
    assert rows[1] == ("tB", "20")
    assert rows[2] == ("tC", "30")


def test_legacy_bool_runner_still_works(conn: sqlite3.Connection) -> None:
    t = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [t])

    run_id = run_workflow(wf, {}, time.time, lambda _t: True, conn)
    assert t.state == TaskState.SUCCEEDED

    cur = conn.execute("SELECT output_json FROM task_outputs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] is None


def test_non_json_serializable_output_fails_task(conn: sqlite3.Connection) -> None:
    t = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [t])

    class Unserializable:
        pass

    def runner(_task: Task) -> TaskResult:
        return TaskResult(ok=True, output=Unserializable())

    run_workflow(wf, {}, time.time, runner, conn)
    assert t.state == TaskState.FAILED
    assert t.last_error is not None
    assert "JSON" in t.last_error or "serializ" in t.last_error.lower()


def test_data_flow_survives_resume(conn: sqlite3.Connection) -> None:
    from orchestration_engine.persistence import save_task_output
    from orchestration_engine.runner import _serialize_workflow
    from orchestration_engine.transitions import transition_task

    tA = Task("tA", "wf", "A", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    tB = Task("tB", "wf", "B", "d", ["tA"], TaskState.PENDING, RetryPolicy(2, 1.0))
    wf = Workflow("wf", "wf", "desc", [tA, tB])
    run_id = "interrupted-flow-run"

    tA._run_id = run_id
    tB._run_id = run_id

    _migrate_database(conn)
    conn.execute(
        """
        INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json)
        VALUES (?, ?, 100.0, NULL, 'running', ?)
        """,
        (run_id, "wf", _serialize_workflow(wf)),
    )
    transition_task(tA, TaskState.READY, conn, 100.0)
    tA.attempt_count = 1
    transition_task(tA, TaskState.RUNNING, conn, 101.0)
    transition_task(tA, TaskState.SUCCEEDED, conn, 102.0)
    save_task_output(conn, run_id, "tA", '{"msg": "hello from A"}', None)

    transition_task(tB, TaskState.READY, conn, 103.0)
    tB.attempt_count = 1
    transition_task(tB, TaskState.RUNNING, conn, 104.0)
    conn.commit()

    b_received_inputs = {}

    def resume_runner(task: Task) -> Any:
        if task.task_id == "tB":
            nonlocal b_received_inputs
            b_received_inputs = dict(task.inputs)
            return TaskResult(ok=True, output="B finished")
        return True

    status = resume_run(conn, run_id, resume_runner, time.time)
    assert status == WorkflowStatus.SUCCEEDED
    assert b_received_inputs == {"tA": {"msg": "hello from A"}}


def test_hooks_lifecycle_called_in_order(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import Hooks

    events: list[str] = []

    hooks = Hooks(
        on_task_start=lambda t: events.append(f"start:{t.task_id}"),
        on_task_succeeded=lambda t: events.append(f"succeeded:{t.task_id}"),
        on_task_failed=lambda t: events.append(f"failed:{t.task_id}"),
        on_task_retry=lambda t: events.append(f"retry:{t.task_id}"),
        on_workflow_done=lambda _wf, st: events.append(f"done:{st.value}"),
    )

    t = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [t])

    run_workflow(wf, {}, time.time, lambda _t: True, conn, hooks=hooks)
    assert events == ["start:t1", "succeeded:t1", "done:succeeded"]


def test_raising_hook_does_not_break_run(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import Hooks

    def broken_hook(_t: Task) -> None:
        raise RuntimeError("boom in hook")

    hooks = Hooks(
        on_task_start=broken_hook,
        on_task_succeeded=broken_hook,
        on_task_failed=broken_hook,
        on_task_retry=broken_hook,
        on_workflow_done=lambda _wf, _st: (_ for _ in ()).throw(RuntimeError("boom done")),
    )

    t = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(1, 1.0))
    wf = Workflow("wf", "wf", "desc", [t])

    # Must complete successfully despite all hooks raising
    run_workflow(wf, {}, time.time, lambda _t: True, conn, hooks=hooks)
    assert t.state == TaskState.SUCCEEDED


def test_hooks_retry_and_failed(conn: sqlite3.Connection) -> None:
    from orchestration_engine.models import Hooks

    events: list[str] = []

    hooks = Hooks(
        on_task_start=lambda t: events.append(f"start:{t.attempt_count}"),
        on_task_retry=lambda t: events.append(f"retry:{t.attempt_count}"),
        on_task_failed=lambda t: events.append(f"failed:{t.attempt_count}"),
        on_workflow_done=lambda _wf, st: events.append(f"done:{st.value}"),
    )

    t = Task("t1", "wf", "T1", "d", [], TaskState.PENDING, RetryPolicy(2, 0.01))
    wf = Workflow("wf", "wf", "desc", [t])

    # Always fails
    run_workflow(wf, {}, time.time, lambda _t: False, conn, hooks=hooks)
    assert t.state == TaskState.FAILED
    assert events == [
        "start:1",
        "retry:1",
        "start:2",
        "failed:2",
        "done:failed",
    ]


def test_workflow_builder_fluent() -> None:
    from orchestration_engine.builder import WorkflowBuilder

    wf = (
        WorkflowBuilder("my-wf", "My Workflow")
        .description("Detailed description")
        .default_timeout(45.0)
        .task("t1", "Task 1", "first task", timeout_seconds=15.0)
        .task(
            "t2",
            "Task 2",
            "second task",
            dependencies=["t1"],
            max_attempts=3,
            delay_seconds=2.5,
        )
        .build()
    )

    assert wf.workflow_id == "my-wf"
    assert wf.name == "My Workflow"
    assert wf.description == "Detailed description"
    assert wf.default_timeout_seconds == 45.0
    assert len(wf.tasks) == 2

    t1, t2 = wf.tasks
    assert t1.task_id == "t1"
    assert t1.timeout_seconds == 15.0
    assert t2.task_id == "t2"
    assert t2.dependencies == ["t1"]
    assert t2.retry_policy.max_attempts == 3
    assert t2.retry_policy.delay_seconds == 2.5
    assert t2.timeout_seconds == 45.0  # Inherited workflow default


def test_workflow_builder_validates_on_build() -> None:
    from orchestration_engine.builder import WorkflowBuilder
    from orchestration_engine.errors import WorkflowValidationError

    # Dependency cycle
    builder = (
        WorkflowBuilder("cycle-wf")
        .task("t1", "T1", dependencies=["t2"])
        .task("t2", "T2", dependencies=["t1"])
    )

    with pytest.raises(WorkflowValidationError, match="cycle"):
        builder.build()


def test_workflow_to_dict_round_trip() -> None:
    from orchestration_engine.builder import WorkflowBuilder, workflow_to_dict
    from orchestration_engine.loader import load_workflow_from_json

    original_wf = (
        WorkflowBuilder("round-trip-wf", "Round Trip", "Testing round trip")
        .default_timeout(60.0)
        .task("extract", "Extract Data", "Fetch data", timeout_seconds=10.0)
        .task(
            "transform",
            "Transform Data",
            "Clean data",
            dependencies=["extract"],
            max_attempts=2,
            delay_seconds=5.0,
            timeout_seconds=20.0,
        )
        .task("load", "Load Data", "Store data", dependencies=["transform"])
        .build()
    )

    wf_dict = workflow_to_dict(original_wf)
    round_trip_wf = load_workflow_from_json(wf_dict)

    assert round_trip_wf.workflow_id == original_wf.workflow_id
    assert round_trip_wf.name == original_wf.name
    assert round_trip_wf.description == original_wf.description
    assert round_trip_wf.default_timeout_seconds == original_wf.default_timeout_seconds
    assert len(round_trip_wf.tasks) == len(original_wf.tasks)

    for orig_t, rt_t in zip(original_wf.tasks, round_trip_wf.tasks, strict=True):
        assert rt_t.task_id == orig_t.task_id
        assert rt_t.workflow_id == orig_t.workflow_id
        assert rt_t.name == orig_t.name
        assert rt_t.description == orig_t.description
        assert rt_t.dependencies == orig_t.dependencies
        assert rt_t.state == orig_t.state
        assert rt_t.retry_policy.max_attempts == orig_t.retry_policy.max_attempts
        assert rt_t.retry_policy.delay_seconds == orig_t.retry_policy.delay_seconds
        assert rt_t.timeout_seconds == orig_t.timeout_seconds


def test_workflow_schema_json_packaged() -> None:
    import json
    from pathlib import Path

    import orchestration_engine

    pkg_dir = Path(orchestration_engine.__file__).parent
    schema_path = pkg_dir / "workflow.schema.json"
    assert schema_path.exists(), f"Schema file not found at {schema_path}"

    with open(schema_path) as f:
        schema = json.load(f)
    assert "$schema" in schema
    assert "properties" in schema
    assert "tasks" in schema["properties"]


def test_load_workflow_collect_errors() -> None:
    from orchestration_engine.errors import WorkflowDefinitionError
    from orchestration_engine.loader import load_workflow_from_json

    invalid_data = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "workflow_id": "wf-invalid",
        # missing "name"
        # missing "description"
        "default_timeout_seconds": -5.0,  # negative timeout
        "tasks": [
            {
                # missing "task_id"
                "name": "Task 1",
                "description": "desc",
                "dependencies": "not-a-list",  # invalid dependencies
                "retry_policy": {
                    "max_attempts": 0,  # invalid
                    "delay_seconds": -1.0,  # invalid
                },
                "timeout_seconds": "not-a-number",  # invalid
            }
        ],
    }

    # Default fail-fast raises on first error
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json(invalid_data, collect_errors=False)
    assert not exc_info.value.errors  # default empty list

    # collect_errors=True collects all errors
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json(invalid_data, collect_errors=True)

    errs = exc_info.value.errors
    assert len(errs) >= 5
    # Verify JSON pointer paths
    assert any("/name" in e for e in errs)
    assert any("/description" in e for e in errs)
    assert any("/default_timeout_seconds" in e for e in errs)
    assert any("/tasks/0/task_id" in e for e in errs)
    assert any("/tasks/0/dependencies" in e for e in errs)
    assert any("/tasks/0/retry_policy/max_attempts" in e for e in errs)
    assert any("/tasks/0/retry_policy/delay_seconds" in e for e in errs)
    assert any("/tasks/0/timeout_seconds" in e for e in errs)


def test_load_workflow_ignores_unknown_keys() -> None:
    from orchestration_engine.loader import load_workflow_from_json

    data = {
        "$schema": "https://example.com/schema",
        "workflow_id": "wf-extra",
        "name": "Extra Keys WF",
        "description": "desc",
        "author": "someone",
        "version_tag": "1.2.3",
        "tasks": [
            {
                "task_id": "t1",
                "name": "T1",
                "description": "desc",
                "dependencies": [],
                "retry_policy": {"max_attempts": 1, "delay_seconds": 1.0, "jitter": True},
                "annotations": {"priority": "high"},
            }
        ],
    }
    wf = load_workflow_from_json(data)
    assert wf.workflow_id == "wf-extra"
    assert len(wf.tasks) == 1
    assert wf.tasks[0].task_id == "t1"


def test_load_workflow_from_yaml_missing_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from orchestration_engine.errors import OrchestrationError
    from orchestration_engine.loader import load_workflow_from_yaml

    # Simulate missing PyYAML
    monkeypatch.setitem(sys.modules, "yaml", None)

    with pytest.raises(OrchestrationError, match="orchestration-engine\\[yaml\\]"):
        load_workflow_from_yaml("workflow_id: foo")


def test_load_workflow_from_yaml_success(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    from orchestration_engine.loader import load_workflow_from_yaml

    yaml_content = """
workflow_id: yaml-wf
name: YAML Workflow
description: Defined in YAML
default_timeout_seconds: 15.0
tasks:
  - task_id: step1
    name: Step 1
    description: First YAML step
    dependencies: []
    retry_policy:
      max_attempts: 2
      delay_seconds: 1.5
    timeout_seconds: 10.0
"""
    # From string
    wf_from_str = load_workflow_from_yaml(yaml_content)
    assert wf_from_str.workflow_id == "yaml-wf"
    assert len(wf_from_str.tasks) == 1
    assert wf_from_str.tasks[0].task_id == "step1"
    assert wf_from_str.tasks[0].retry_policy.max_attempts == 2

    # From file
    yaml_file = tmp_path / "workflow.yaml"
    yaml_file.write_text(yaml_content)
    wf_from_file = load_workflow_from_yaml(yaml_file)
    assert wf_from_file.workflow_id == "yaml-wf"


def test_load_workflow_from_yaml_invalid_mapping() -> None:
    pytest.importorskip("yaml")
    from orchestration_engine.errors import WorkflowDefinitionError
    from orchestration_engine.loader import load_workflow_from_yaml

    with pytest.raises(WorkflowDefinitionError, match="mapping"):
        load_workflow_from_yaml("- item 1\n- item 2\n")


def test_builder_methods_and_explicit_retry_policy() -> None:
    from orchestration_engine.builder import WorkflowBuilder

    custom_policy = RetryPolicy(max_attempts=5, delay_seconds=10.0)
    wf = (
        WorkflowBuilder("b-wf")
        .name("Explicit Name")
        .task("t1", retry_policy=custom_policy)
        .build()
    )
    assert wf.name == "Explicit Name"
    assert wf.tasks[0].retry_policy == custom_policy


def test_load_workflow_from_yaml_stream() -> None:
    import io
    pytest.importorskip("yaml")
    from orchestration_engine.loader import load_workflow_from_yaml

    stream = io.StringIO("workflow_id: stream-wf\nname: Stream\ndescription: d\ntasks: []\n")
    wf = load_workflow_from_yaml(stream)
    assert wf.workflow_id == "stream-wf"


def test_load_workflow_collect_errors_comprehensive() -> None:
    from orchestration_engine.errors import WorkflowDefinitionError
    from orchestration_engine.loader import load_workflow_from_json

    # Test missing tasks key
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json({}, collect_errors=True)
    assert any("/tasks: missing required field" in e for e in exc_info.value.errors)

    # Test tasks not a list
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json(
            {"workflow_id": "w", "name": "n", "description": "d", "tasks": "invalid"},
            collect_errors=True,
        )
    assert any("/tasks: must be a list" in e for e in exc_info.value.errors)

    # Test task element not an object
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json(
            {"workflow_id": "w", "name": "n", "description": "d", "tasks": ["not-a-dict"]},
            collect_errors=True,
        )
    assert any("/tasks/0: must be an object" in e for e in exc_info.value.errors)

    # Test non-string top-level and task fields, and invalid retry_policy type
    bad_types = {
        "workflow_id": 123,
        "name": 456,
        "description": 789,
        "tasks": [
            {
                "task_id": 101,
                "name": 102,
                "description": 103,
                "dependencies": [999],  # non-string dep
                "retry_policy": "not-a-dict",  # non-dict retry policy
            },
            {
                "task_id": "t2",
                "name": "T2",
                "description": "d",
                "dependencies": [],
                "retry_policy": {},  # missing max_attempts and delay_seconds
            },
        ],
    }
    with pytest.raises(WorkflowDefinitionError) as exc_info:
        load_workflow_from_json(bad_types, collect_errors=True)
    errs = exc_info.value.errors
    assert any("/workflow_id: must be a non-empty string" in e for e in errs)
    assert any("/name: must be a string" in e for e in errs)
    assert any("/description: must be a string" in e for e in errs)
    assert any("/tasks/0/task_id: must be a non-empty string" in e for e in errs)
    assert any("/tasks/0/name: must be a string" in e for e in errs)
    assert any("/tasks/0/description: must be a string" in e for e in errs)
    assert any("/tasks/0/dependencies/0: must be a string" in e for e in errs)
    assert any("/tasks/0/retry_policy: must be an object" in e for e in errs)
    assert any("/tasks/1/retry_policy/max_attempts: missing required field" in e for e in errs)
    assert any("/tasks/1/retry_policy/delay_seconds: missing required field" in e for e in errs)





