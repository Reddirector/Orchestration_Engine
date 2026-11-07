"""
Unit tests for Work Stealing & Dead Worker Reclamation.
"""

from orchestration_engine.stealing import WorkStealingRegistry


def test_work_stealing_registration_and_heartbeat() -> None:
    registry = WorkStealingRegistry(":memory:")
    registry.register_worker("w1", capacity=4, host="10.0.0.1", port=9001, time_source=100.0)

    worker = registry.get_worker("w1")
    assert worker is not None
    assert worker.worker_id == "w1"
    assert worker.capacity == 4
    assert worker.last_heartbeat == 100.0
    assert worker.status == "ALIVE"

    registry.heartbeat("w1", active_tasks=["t1", "t2"], time_source=120.0)
    worker = registry.get_worker("w1")
    assert worker is not None
    assert worker.last_heartbeat == 120.0
    assert worker.active_tasks == ["t1", "t2"]


def test_work_stealing_rebalance() -> None:
    registry = WorkStealingRegistry(":memory:")
    registry.register_worker("w_heavy", capacity=4, time_source=100.0)
    registry.register_worker("w_idle", capacity=4, time_source=100.0)

    # Queue 4 tasks on w_heavy
    for i in range(4):
        registry.enqueue_task(
            f"task_{i}",
            assigned_worker_id="w_heavy",
            state="READY",
            time_source=100.0 + i,
        )

    assert len(registry.get_assigned_tasks("w_heavy")) == 4
    assert len(registry.get_assigned_tasks("w_idle")) == 0

    # w_idle steals 2 tasks
    stolen = registry.steal_work("w_idle", max_tasks=2, time_source=150.0)
    assert len(stolen) == 2

    assert len(registry.get_assigned_tasks("w_heavy")) == 2
    assert len(registry.get_assigned_tasks("w_idle")) == 2


def test_dead_worker_reclamation() -> None:
    registry = WorkStealingRegistry(":memory:")
    registry.register_worker("w_crashed", capacity=2, time_source=100.0)
    registry.register_worker("w_healthy", capacity=2, time_source=200.0)

    registry.enqueue_task(
        "task_orphaned",
        assigned_worker_id="w_crashed",
        state="RUNNING",
        time_source=100.0,
    )

    # Reclaim with now=200.0, timeout=50.0 -> w_crashed (last_hb 100.0) is dead
    reclaimed = registry.reclaim_dead_workers(timeout_seconds=50.0, time_source=200.0)
    assert reclaimed == ["task_orphaned"]

    crashed = registry.get_worker("w_crashed")
    assert crashed is not None
    assert crashed.status == "DEAD"

    # task_orphaned is now unassigned & READY; w_healthy can grab it
    stolen = registry.steal_work("w_healthy", max_tasks=1, time_source=205.0)
    assert stolen == ["task_orphaned"]
    assert registry.get_assigned_tasks("w_healthy") == ["task_orphaned"]
