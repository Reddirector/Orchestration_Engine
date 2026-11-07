"""Tests for Hierarchical Sub-Workflows and Nested DAGs."""

from __future__ import annotations

from typing import Any

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult, WorkflowStatus
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow
from orchestration_engine.status import get_run_status
from orchestration_engine.subworkflows import (
    execute_subworkflow,
    get_subworkflow_tree,
    make_subworkflow_runner,
)


def test_execute_subworkflow_success() -> None:
    conn = get_connection(":memory:")

    # 1. Build child workflow
    child_wf = (
        WorkflowBuilder("child-wf")
        .task("child_step1", name="Step 1")
        .task("child_step2", name="Step 2", dependencies=["child_step1"])
        .build()
    )

    def child_runner(task: Task) -> TaskResult:
        if task.task_id == "child_step1":
            return TaskResult(ok=True, output={"val": 42})
        return TaskResult(ok=True, output={"result": "child-success"})

    parent_task = (
        WorkflowBuilder("dummy_parent")
        .task("parent_embed", name="Embedded Subworkflow")
        .build()
        .tasks[0]
    )
    parent_task.inputs["parent_param"] = "root_data"

    res = execute_subworkflow(
        conn=conn,
        parent_run_id="parent-run-101",
        parent_task=parent_task,
        subworkflow=child_wf,
        task_runner=child_runner,
    )

    assert res.ok is True
    assert isinstance(res.output, dict)
    assert res.output["status"] == WorkflowStatus.SUCCEEDED.value
    assert res.output["outputs"]["child_step1"] == {"val": 42}
    assert res.output["outputs"]["child_step2"] == {"result": "child-success"}

    # Verify tree inspection
    tree = get_subworkflow_tree(conn, "parent-run-101")
    assert tree["run_id"] == "parent-run-101"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["workflow_id"] == "child-wf"
    assert tree["children"][0]["status"] == WorkflowStatus.SUCCEEDED.value


def test_execute_subworkflow_failure() -> None:
    conn = get_connection(":memory:")

    child_wf = (
        WorkflowBuilder("failing-child")
        .task("fail_step", name="Will Fail")
        .build()
    )

    def failing_runner(task: Task) -> TaskResult:
        return TaskResult(ok=False, error="child process exception")

    parent_task = (
        WorkflowBuilder("dummy_parent")
        .task("parent_task", name="Parent Container")
        .build()
        .tasks[0]
    )
    res = execute_subworkflow(
        conn=conn,
        parent_run_id="parent-run-202",
        parent_task=parent_task,
        subworkflow=child_wf,
        task_runner=failing_runner,
    )

    assert res.ok is False
    assert "failed" in (res.error or "")


def test_make_subworkflow_runner_integration(tmp_path: Any) -> None:
    db_file = str(tmp_path / "subwf_integration.db")
    conn = get_connection(db_file)

    # Child workflow
    sub_wf = (
        WorkflowBuilder("inner-pipeline")
        .task("sub_a", name="Sub A")
        .build()
    )

    def inner_runner(task: Task) -> TaskResult:
        return TaskResult(ok=True, output={"echo": task.inputs.get("msg", "default")})

    child_runner_fn = make_subworkflow_runner(
        subworkflow=sub_wf,
        child_task_runner=inner_runner,
        conn_factory=lambda: get_connection(db_file),
    )

    # Parent workflow
    parent_wf = (
        WorkflowBuilder("parent-pipeline")
        .task("outer_task", name="Runs Subworkflow")
        .build()
    )

    def parent_runner(t: Task) -> TaskResult:
        t.inputs["msg"] = "hello from parent"
        return child_runner_fn(t)

    parent_run_id = run_workflow(
        workflow=parent_wf,
        task_states={t.task_id: t.state for t in parent_wf.tasks},
        time_source=lambda: 1000.0,
        task_runner=parent_runner,
        conn=conn,
    )

    status = get_run_status(conn, parent_run_id)
    assert status == WorkflowStatus.SUCCEEDED

    tree = get_subworkflow_tree(conn, parent_run_id)
    assert len(tree["children"]) >= 1
    assert tree["children"][0]["workflow_id"] == "inner-pipeline"
