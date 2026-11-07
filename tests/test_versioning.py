"""Tests for Semantic Workflow Versioning and Migration."""

from __future__ import annotations

import json

from orchestration_engine.builder import WorkflowBuilder, workflow_to_dict
from orchestration_engine.versioning import (
    MigrationPolicy,
    WorkflowVersionRegistry,
    compare_workflows,
    compute_workflow_hash,
)


def test_compute_workflow_hash_determinism() -> None:
    # Build wf1 with tasks (a, b)
    wf1 = (
        WorkflowBuilder("wf-1")
        .task("a")
        .task("b", dependencies=["a"])
        .build()
    )

    # Build wf2 with tasks in reverse order (b, a)
    wf2 = (
        WorkflowBuilder("wf-1")
        .task("b", dependencies=["a"])
        .task("a")
        .build()
    )

    h1 = compute_workflow_hash(wf1)
    h2 = compute_workflow_hash(wf2)
    assert len(h1) == 16
    assert h1 == h2, "Task declaration order should not affect the deterministic hash"

    # Modifying retry policy changes the hash
    wf3 = (
        WorkflowBuilder("wf-1")
        .task("a", max_attempts=5)
        .task("b", dependencies=["a"])
        .build()
    )
    assert compute_workflow_hash(wf3) != h1


def test_compare_workflows_diff() -> None:
    v1 = (
        WorkflowBuilder("app")
        .task("ingest")
        .task("process", dependencies=["ingest"])
        .build()
    )

    # v2 appends a non-breaking 'notify' step
    v2 = (
        WorkflowBuilder("app")
        .task("ingest")
        .task("process", dependencies=["ingest"])
        .task("notify", dependencies=["process"])
        .build()
    )

    diff = compare_workflows(v1, v2)
    assert diff.added_tasks == {"notify"}
    assert diff.removed_tasks == set()
    assert diff.is_backward_compatible is True

    # v3 removes 'ingest' (breaking)
    v3 = (
        WorkflowBuilder("app")
        .task("process")
        .build()
    )
    diff_breaking = compare_workflows(v1, v3)
    assert diff_breaking.removed_tasks == {"ingest"}
    assert diff_breaking.is_backward_compatible is False


def test_version_registry_and_migration_policies() -> None:
    registry = WorkflowVersionRegistry()
    wf_v1 = (
        WorkflowBuilder("pipeline")
        .task("t1")
        .task("t2", dependencies=["t1"])
        .build()
    )
    wf_v2 = (
        WorkflowBuilder("pipeline")
        .task("t1")
        .task("t2", dependencies=["t1"])
        .task("t3", dependencies=["t2"])
        .build()
    )

    h1 = registry.register(wf_v1)
    h2 = registry.register(wf_v2)
    assert h1 != h2
    assert registry.get("pipeline", h1) == wf_v1
    assert registry.list_versions("pipeline") == [h1, h2]

    v1_json = json.dumps(workflow_to_dict(wf_v1))

    # 1. Fail Fast: should reject running against active wf_v2
    ok, reason = registry.check_migration(wf_v2, v1_json, MigrationPolicy.FAIL_FAST)
    assert ok is False
    assert "Version mismatch" in reason

    # 2. Drain: should permit running old run under v1
    ok, reason = registry.check_migration(wf_v2, v1_json, MigrationPolicy.DRAIN)
    assert ok is True
    assert "Drain permitted" in reason

    # 3. Auto Migrate: should permit since v2 only added t3
    ok, reason = registry.check_migration(wf_v2, v1_json, MigrationPolicy.AUTO_MIGRATE)
    assert ok is True
    assert "Auto-migration permitted" in reason
