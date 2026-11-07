"""
Unit tests for Multi-Tenant Fair-Share & Hierarchical Quota Engine.
"""

import pytest

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.quotas import (
    TenantQuota,
    TenantQuotaExceededError,
    TenantQuotaManager,
)


def test_tenant_quota_concurrency_limiting() -> None:
    mgr = TenantQuotaManager()
    mgr.set_quota(TenantQuota(tenant_id="tenant_a", max_concurrent=2, rate_limit_per_second=100.0))

    # Acquire 2 slots
    assert mgr.acquire("tenant_a", time_source=100.0) is True
    assert mgr.acquire("tenant_a", time_source=100.0) is True

    # 3rd acquire fails due to max_concurrent=2
    assert mgr.acquire("tenant_a", time_source=100.0) is False

    # Release 1 slot
    mgr.release("tenant_a")
    assert mgr.acquire("tenant_a", time_source=100.0) is True


def test_tenant_quota_rate_limiting() -> None:
    mgr = TenantQuotaManager()
    mgr.set_quota(
        TenantQuota(
            tenant_id="tenant_b",
            max_concurrent=10,
            rate_limit_per_second=5.0,
            burst_capacity=2.0,
        )
    )

    # 2 tokens available in burst
    assert mgr.acquire("tenant_b", time_source=100.0) is True
    mgr.release("tenant_b")

    assert mgr.acquire("tenant_b", time_source=100.0) is True
    mgr.release("tenant_b")

    # Burst exhausted at t=100.0
    assert mgr.acquire("tenant_b", time_source=100.0) is False

    # Refill at t=100.5 (0.5s * 5 tokens/s = 2.5 tokens refill)
    assert mgr.acquire("tenant_b", time_source=100.5) is True
    mgr.release("tenant_b")


def test_wrap_tenant_task() -> None:
    mgr = TenantQuotaManager()
    mgr.set_quota(TenantQuota(tenant_id="tenant_c", max_concurrent=1, rate_limit_per_second=10.0))

    task = WorkflowBuilder("wf").task("t1", name="Task 1").build().tasks[0]

    def runner(t: Task) -> TaskResult:
        return TaskResult(ok=True, output={"done": True})

    wrapped = mgr.wrap_tenant_task("tenant_c", runner, raise_on_quota=False)

    # First task passes
    res = wrapped(task)
    assert res.ok is True
    assert res.output == {"done": True}

    # Simulate quota exhaustion by manually holding the slot
    assert mgr.acquire("tenant_c") is True

    res2 = wrapped(task)
    assert res2.ok is False
    assert "quota exceeded" in (res2.error or "")

    wrapped_raise = mgr.wrap_tenant_task("tenant_c", runner, raise_on_quota=True)
    with pytest.raises(TenantQuotaExceededError):
        wrapped_raise(task)

    mgr.release("tenant_c")
