"""Unit tests for run_workflow_multiprocess."""

from __future__ import annotations

import sqlite3

import pytest

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.errors import WorkflowValidationError
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.process_runner import run_workflow_multiprocess


# Module-level picklable task runner
def _multiprocess_test_runner(task: Task) -> TaskResult:
    return TaskResult(ok=True, output=f"proc-{task.task_id}")


def test_process_runner_e2e(conn: sqlite3.Connection) -> None:
    wf = (
        WorkflowBuilder("multiprocess-wf")
        .task("calc1", name="Calculate Part 1")
        .task("calc2", name="Calculate Part 2")
        .task("merge", name="Merge Parts", dependencies=["calc1", "calc2"])
        .build()
    )

    run_id = run_workflow_multiprocess(
        workflow=wf,
        task_runner=_multiprocess_test_runner,
        conn=conn,
        max_concurrency=2,
    )
    assert run_id is not None
    assert len(run_id) > 0


def test_process_runner_defaults() -> None:
    wf = WorkflowBuilder("default-proc-wf").task("a").build()
    run_id = run_workflow_multiprocess(wf, _multiprocess_test_runner)
    assert run_id is not None


def test_process_runner_unpicklable() -> None:
    wf = WorkflowBuilder("fail-wf").task("a").build()
    # Unpicklable lambda / local closure
    unpicklable = lambda t: True  # noqa: E731

    with pytest.raises(WorkflowValidationError) as exc:
        run_workflow_multiprocess(wf, unpicklable)
    assert "must be picklable" in str(exc.value)
