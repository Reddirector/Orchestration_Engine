"""Tests for Dynamic Conditional Branching and Decision Trees."""

from __future__ import annotations

from orchestration_engine.branching import (
    apply_branch_decision,
    evaluate_branch,
)
from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import TaskState


def test_evaluate_branch_and_apply_decision() -> None:
    wf = (
        WorkflowBuilder("branch-wf")
        .task("eval_risk")
        .task("fast_approval", dependencies=["eval_risk"])
        .task("auto_transfer", dependencies=["fast_approval"])
        .task("manual_review", dependencies=["eval_risk"])
        .task("compliance_audit", dependencies=["manual_review"])
        .task("notify_user", dependencies=["auto_transfer", "compliance_audit"])
        .build()
    )

    # 1. Output score is low risk (0.1) -> route to fast_approval
    output_low_risk = {"risk_score": 0.1}

    def router(out: dict[str, float]) -> list[str]:
        if out["risk_score"] < 0.5:
            return ["fast_approval"]
        return ["manual_review"]

    decision = evaluate_branch(wf, "eval_risk", output_low_risk, router)

    assert decision.active_task_ids == ["fast_approval"]
    # manual_review and its exclusive child compliance_audit should be marked as skipped
    assert "manual_review" in decision.skipped_task_ids
    assert "compliance_audit" in decision.skipped_task_ids
    assert "fast_approval" not in decision.skipped_task_ids
    assert "auto_transfer" not in decision.skipped_task_ids

    task_states: dict[str, TaskState] = {"eval_risk": TaskState.SUCCEEDED}
    apply_branch_decision(task_states, decision)

    assert task_states["manual_review"] == TaskState.CANCELLED
    assert task_states["compliance_audit"] == TaskState.CANCELLED
    assert "fast_approval" not in task_states


def test_evaluate_branch_high_risk_path() -> None:
    wf = (
        WorkflowBuilder("branch-wf-2")
        .task("eval_risk")
        .task("fast_approval", dependencies=["eval_risk"])
        .task("manual_review", dependencies=["eval_risk"])
        .build()
    )

    output_high = {"risk_score": 0.9}

    def router(out: dict[str, float]) -> list[str]:
        if out["risk_score"] < 0.5:
            return ["fast_approval"]
        return ["manual_review"]

    decision = evaluate_branch(wf, "eval_risk", output_high, router)
    assert decision.active_task_ids == ["manual_review"]
    assert decision.skipped_task_ids == ["fast_approval"]
