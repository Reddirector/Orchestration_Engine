"""Tests for Priority Scheduling and Multi-Tenant Fair Queuing."""

from __future__ import annotations

from orchestration_engine.priority import PriorityTaskQueue, TaskPriority


def test_priority_ordering() -> None:
    queue = PriorityTaskQueue()

    queue.push("batch-1", priority=TaskPriority.BATCH)
    queue.push("critical-1", priority=TaskPriority.CRITICAL)
    queue.push("default-1", priority=TaskPriority.DEFAULT)
    queue.push("high-1", priority=TaskPriority.HIGH)

    assert len(queue) == 4

    p1 = queue.pop()
    assert p1 is not None and p1[0] == "critical-1"

    p2 = queue.pop()
    assert p2 is not None and p2[0] == "high-1"

    p3 = queue.pop()
    assert p3 is not None and p3[0] == "default-1"

    p4 = queue.pop()
    assert p4 is not None and p4[0] == "batch-1"

    assert len(queue) == 0
    assert queue.pop() is None


def test_multi_tenant_fair_quota_and_starvation_prevention() -> None:
    # Tenant A has quota = 1
    # Tenant B has quota = 5
    queue = PriorityTaskQueue(default_tenant_max_concurrency=5)
    queue.set_tenant_quota("tenant-a", 1)

    # Tenant A pushes 3 critical tasks
    queue.push("a-1", priority=TaskPriority.CRITICAL, tenant_id="tenant-a")
    queue.push("a-2", priority=TaskPriority.CRITICAL, tenant_id="tenant-a")
    queue.push("a-3", priority=TaskPriority.CRITICAL, tenant_id="tenant-a")

    # Tenant B pushes 1 high task
    queue.push("b-1", priority=TaskPriority.HIGH, tenant_id="tenant-b")

    # First pop picks a-1
    task_a1 = queue.pop()
    assert task_a1 is not None and task_a1[0] == "a-1"
    assert queue.active_count("tenant-a") == 1

    # Second pop cannot pick a-2 because tenant-a has reached max concurrency 1!
    # It must pick b-1 instead, preventing starvation!
    task_b1 = queue.pop()
    assert task_b1 is not None and task_b1[0] == "b-1"
    assert queue.active_count("tenant-b") == 1

    # Acknowledging a-1 frees up tenant-a's slot
    queue.acknowledge("tenant-a")
    assert queue.active_count("tenant-a") == 0

    task_a2 = queue.pop()
    assert task_a2 is not None and task_a2[0] == "a-2"
