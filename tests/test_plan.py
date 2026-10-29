"""Tests for Workflow Execution Plan and Critical Path Analyzer."""

from __future__ import annotations

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.plan import generate_execution_plan


def test_generate_execution_plan_stages_and_critical_path() -> None:
    # Diamond graph:
    #       t1
    #     /    \
    #    t2    t3
    #     \    /
    #       t4
    wf = (
        WorkflowBuilder("diamond-wf")
        .task("t1")
        .task("t2", dependencies=["t1"])
        .task("t3", dependencies=["t1"])
        .task("t4", dependencies=["t2", "t3"])
        .build()
    )

    plan = generate_execution_plan(wf)

    assert plan.workflow_id == "diamond-wf"
    assert plan.total_tasks == 4
    assert plan.max_parallelism == 2  # Stage 1 has t2 and t3 concurrently
    assert len(plan.stages) == 3

    assert plan.stages[0].stage_index == 0
    assert plan.stages[0].task_ids == ["t1"]

    assert plan.stages[1].stage_index == 1
    assert set(plan.stages[1].task_ids) == {"t2", "t3"}

    assert plan.stages[2].stage_index == 2
    assert plan.stages[2].task_ids == ["t4"]

    assert len(plan.critical_path) == 3  # t1 -> (t2 or t3) -> t4
    assert plan.critical_path[0] == "t1"
    assert plan.critical_path[2] == "t4"

    # to_dict
    d = plan.to_dict()
    assert d["workflow_id"] == "diamond-wf"
    assert d["total_tasks"] == 4
    assert d["max_parallelism"] == 2
