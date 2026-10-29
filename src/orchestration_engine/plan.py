"""Execution Plan and Topological Critical Path Analyzer.

Provides dry-run simulation, parallel stage partitioning, and dependency
analysis for workflows without executing side effects.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from orchestration_engine.models import Workflow


@dataclasses.dataclass(frozen=True)
class ExecutionStage:
    """A set of independent tasks that can execute concurrently."""

    stage_index: int
    task_ids: list[str]


@dataclasses.dataclass(frozen=True)
class ExecutionPlan:
    """Static execution plan and topological breakdown of a workflow."""

    workflow_id: str
    total_tasks: int
    stages: list[ExecutionStage]
    max_parallelism: int
    critical_path: list[str]
    dependency_graph: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "total_tasks": self.total_tasks,
            "max_parallelism": self.max_parallelism,
            "critical_path": self.critical_path,
            "stages": [
                {"stage_index": s.stage_index, "task_ids": s.task_ids}
                for s in self.stages
            ],
            "dependency_graph": self.dependency_graph,
        }


def generate_execution_plan(workflow: Workflow) -> ExecutionPlan:
    """Compute the topological execution stages and critical path for a workflow.

    Args:
        workflow: The workflow to analyze.

    Returns:
        ExecutionPlan detailing parallel execution stages and critical path.
    """
    tasks = workflow.tasks
    task_map = {t.task_id: t for t in tasks}
    dependency_graph = {t.task_id: list(t.dependencies) for t in tasks}

    # Group into topological stages
    stages: list[ExecutionStage] = []
    completed: set[str] = set()

    stage_idx = 0
    while len(completed) < len(tasks):
        ready = [
            t.task_id
            for t in tasks
            if t.task_id not in completed
            and all(dep in completed for dep in t.dependencies)
        ]
        if not ready:
            # Fallback for disconnected / cyclic (validation already guarantees acyclic)
            break

        stages.append(ExecutionStage(stage_index=stage_idx, task_ids=ready))
        completed.update(ready)
        stage_idx += 1

    max_parallelism = max((len(s.task_ids) for s in stages), default=0)

    # Compute longest critical path (in terms of task count)
    def get_longest_path(task_id: str) -> list[str]:
        t = task_map[task_id]
        if not t.dependencies:
            return [task_id]
        best_parent_path: list[str] = []
        for dep in t.dependencies:
            p = get_longest_path(dep)
            if len(p) > len(best_parent_path):
                best_parent_path = p
        return best_parent_path + [task_id]

    longest_path: list[str] = []
    for t in tasks:
        p = get_longest_path(t.task_id)
        if len(p) > len(longest_path):
            longest_path = p

    return ExecutionPlan(
        workflow_id=workflow.workflow_id,
        total_tasks=len(tasks),
        stages=stages,
        max_parallelism=max_parallelism,
        critical_path=longest_path,
        dependency_graph=dependency_graph,
    )
