"""Semantic Workflow Versioning, Drift Detection, and Run Migration.

Provides deterministic topology hashing to detect code drift between active definitions
and persisted in-flight runs, with configurable migration policies (FAIL_FAST, DRAIN, AUTO_MIGRATE).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from orchestration_engine.loader import load_workflow_from_json
from orchestration_engine.models import Workflow


class MigrationPolicy(StrEnum):
    """Policy applied when an in-flight run encounters code version drift."""

    FAIL_FAST = "fail_fast"
    DRAIN = "drain"
    AUTO_MIGRATE = "auto_migrate"


@dataclass(frozen=True)
class VersionDiff:
    """Structural difference between two workflow versions."""

    added_tasks: set[str]
    removed_tasks: set[str]
    modified_dependencies: dict[str, tuple[list[str], list[str]]]
    is_backward_compatible: bool


def compute_workflow_hash(workflow: Workflow) -> str:
    """Compute a deterministic 16-character SHA-256 fingerprint for a workflow definition."""
    canonical_repr: dict[str, Any] = {
        "workflow_id": workflow.workflow_id,
        "tasks": [],
    }

    # Sort tasks by task_id to ensure order independence
    for t in sorted(workflow.tasks, key=lambda x: x.task_id):
        canonical_repr["tasks"].append(
            {
                "task_id": t.task_id,
                "dependencies": sorted(t.dependencies),
                "max_attempts": t.retry_policy.max_attempts,
                "delay_seconds": t.retry_policy.delay_seconds,
                "timeout_seconds": t.timeout_seconds,
            }
        )

    serialized = json.dumps(canonical_repr, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def compare_workflows(old_wf: Workflow, new_wf: Workflow) -> VersionDiff:
    """Compare two workflow topologies to evaluate backward compatibility."""
    old_tasks = {t.task_id: t for t in old_wf.tasks}
    new_tasks = {t.task_id: t for t in new_wf.tasks}

    added = set(new_tasks.keys()) - set(old_tasks.keys())
    removed = set(old_tasks.keys()) - set(new_tasks.keys())

    modified_deps: dict[str, tuple[list[str], list[str]]] = {}
    for tid in set(old_tasks.keys()) & set(new_tasks.keys()):
        old_dep = sorted(old_tasks[tid].dependencies)
        new_dep = sorted(new_tasks[tid].dependencies)
        if old_dep != new_dep:
            modified_deps[tid] = (old_dep, new_dep)

    # Compatible only if no tasks removed and no existing dependencies mutated
    is_compatible = len(removed) == 0 and len(modified_deps) == 0

    return VersionDiff(
        added_tasks=added,
        removed_tasks=removed,
        modified_dependencies=modified_deps,
        is_backward_compatible=is_compatible,
    )


class WorkflowVersionRegistry:
    """Registry maintaining versioned workflow definitions and evaluating run migration."""

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, Workflow]] = {}

    def register(self, workflow: Workflow) -> str:
        """Register a workflow and return its version hash."""
        v_hash = compute_workflow_hash(workflow)
        wf_id = workflow.workflow_id
        if wf_id not in self._versions:
            self._versions[wf_id] = {}
        self._versions[wf_id][v_hash] = workflow
        return v_hash

    def get(self, workflow_id: str, version_hash: str) -> Workflow | None:
        """Retrieve a specific version of a workflow."""
        return self._versions.get(workflow_id, {}).get(version_hash)

    def list_versions(self, workflow_id: str) -> list[str]:
        """List all registered version hashes for a workflow."""
        return list(self._versions.get(workflow_id, {}).keys())

    def check_migration(
        self,
        active_workflow: Workflow,
        run_definition_json: str,
        policy: MigrationPolicy = MigrationPolicy.FAIL_FAST,
    ) -> tuple[bool, str]:
        """Check if an in-flight run definition is compatible with active code under a policy.

        Returns:
            (can_proceed, reason_message)
        """
        active_hash = compute_workflow_hash(active_workflow)
        run_dict = json.loads(run_definition_json)
        run_wf = load_workflow_from_json(run_dict)
        run_hash = compute_workflow_hash(run_wf)

        if active_hash == run_hash:
            return True, f"Identical workflow version ({active_hash})"

        if policy == MigrationPolicy.FAIL_FAST:
            return False, f"Version mismatch: active code is {active_hash}, run is {run_hash}"

        if policy == MigrationPolicy.DRAIN:
            return True, f"Drain permitted: run will continue on historical definition {run_hash}"

        # AUTO_MIGRATE
        diff = compare_workflows(run_wf, active_workflow)
        if diff.is_backward_compatible:
            return (
                True,
                f"Auto-migration permitted: {len(diff.added_tasks)} new task(s) appended cleanly",
            )
        deps_desc = list(diff.modified_dependencies.keys())
        return (
            False,
            f"Incompatible schema drift: removed {diff.removed_tasks}, "
            f"modified dependencies {deps_desc}",
        )
