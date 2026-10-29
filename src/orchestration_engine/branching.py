"""Conditional Branching and Dynamic Path Routing.

Enables decision-tree execution, dynamic model routing (e.g. confidence scoring,
fast-path vs slow-path approval), and conditional task activation.
Tasks on unchosen paths are safely marked as SKIPPED so downstream tasks that
depend only on the active branch can proceed smoothly.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from orchestration_engine.models import TaskState, Workflow


@dataclasses.dataclass(frozen=True)
class BranchDecision:
    """Outcome of a dynamic branch routing evaluation."""

    active_task_ids: list[str]
    skipped_task_ids: list[str]


def evaluate_branch(
    workflow: Workflow,
    source_task_id: str,
    output: Any,
    router_fn: Callable[[Any], list[str]],
) -> BranchDecision:
    """Evaluate router_fn against source_task_id's output to choose active branches.

    All candidate downstream tasks of source_task_id not selected by router_fn
    (and their exclusive transitive descendants) are marked as skipped.

    Args:
        workflow: The workflow definition.
        source_task_id: The decision task that completed.
        output: The output payload of source_task_id.
        router_fn: Callable returning the list of active task_ids to execute.

    Returns:
        BranchDecision containing lists of active and skipped task IDs.
    """
    # 1. Identify direct downstream dependencies of source_task_id
    direct_downstreams = [
        t.task_id for t in workflow.tasks if source_task_id in t.dependencies
    ]

    # 2. Call router function to select active task_ids
    chosen_ids = set(router_fn(output))

    # All direct downstreams not chosen are directly skipped
    directly_skipped = [tid for tid in direct_downstreams if tid not in chosen_ids]

    # 3. Compute transitive exclusive descendants of skipped tasks
    all_skipped = set(directly_skipped)

    changed = True
    while changed:
        changed = False
        for t in workflow.tasks:
            if t.task_id in all_skipped or t.task_id in chosen_ids or t.task_id == source_task_id:
                continue
            # If all dependencies of t are in all_skipped, t must also be skipped
            if t.dependencies and all(dep in all_skipped for dep in t.dependencies):
                all_skipped.add(t.task_id)
                changed = True

    return BranchDecision(
        active_task_ids=list(chosen_ids),
        skipped_task_ids=list(all_skipped),
    )


def apply_branch_decision(
    task_states: dict[str, TaskState],
    decision: BranchDecision,
) -> None:
    """Apply the branch decision to the engine's task state dictionary."""
    for tid in decision.skipped_task_ids:
        task_states[tid] = TaskState.CANCELLED
