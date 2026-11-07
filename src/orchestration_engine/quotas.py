"""
Multi-Tenant Fair-Share & Hierarchical Quota Engine for Orchestration Engine.

Enforces per-tenant concurrency limits and token-bucket request rate limits across
multi-tenant clusters, preventing noisy-neighbor resource starvation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from orchestration_engine.errors import OrchestrationError
from orchestration_engine.models import Hooks, Task, TaskResult


class TenantQuotaExceededError(OrchestrationError):
    """Raised when a tenant exceeds their concurrency or rate limit quota."""


@dataclass
class TenantQuota:
    """Configured rate and concurrency bounds for a single tenant."""

    tenant_id: str
    max_concurrent: int = 10
    rate_limit_per_second: float = 100.0
    burst_capacity: float = 10.0


@dataclass
class TenantUsage:
    """Current in-flight usage and token bucket state for a tenant."""

    tenant_id: str
    active_concurrent: int = 0
    available_tokens: float = 10.0
    last_token_refill: float = 0.0


class TenantQuotaManager:
    """Thread-safe multi-tenant quota manager combining concurrency and rate limiting."""

    def __init__(self, default_quota: TenantQuota | None = None) -> None:
        self._lock = threading.Lock()
        self._default_quota = default_quota or TenantQuota(tenant_id="default")
        self._quotas: dict[str, TenantQuota] = {}
        self._usages: dict[str, TenantUsage] = {}

    def set_quota(self, quota: TenantQuota) -> None:
        """Register or update a tenant's quota limits."""
        with self._lock:
            self._quotas[quota.tenant_id] = quota
            if quota.tenant_id not in self._usages:
                self._usages[quota.tenant_id] = TenantUsage(
                    tenant_id=quota.tenant_id,
                    available_tokens=quota.burst_capacity,
                    last_token_refill=time.time(),
                )

    def get_quota(self, tenant_id: str) -> TenantQuota:
        """Fetch configured quota for a tenant or fall back to default."""
        with self._lock:
            return self._quotas.get(
                tenant_id,
                TenantQuota(
                    tenant_id=tenant_id,
                    max_concurrent=self._default_quota.max_concurrent,
                    rate_limit_per_second=self._default_quota.rate_limit_per_second,
                    burst_capacity=self._default_quota.burst_capacity,
                ),
            )

    def get_usage(self, tenant_id: str) -> TenantUsage:
        """Fetch current live usage snapshot for a tenant."""
        with self._lock:
            quota = self.get_quota(tenant_id)
            if tenant_id not in self._usages:
                self._usages[tenant_id] = TenantUsage(
                    tenant_id=tenant_id,
                    available_tokens=quota.burst_capacity,
                    last_token_refill=time.time(),
                )
            usage = self._usages[tenant_id]
            return TenantUsage(
                tenant_id=usage.tenant_id,
                active_concurrent=usage.active_concurrent,
                available_tokens=usage.available_tokens,
                last_token_refill=usage.last_token_refill,
            )

    def acquire(
        self,
        tenant_id: str,
        tokens: float = 1.0,
        time_source: float | None = None,
    ) -> bool:
        """Attempt to acquire execution permission under concurrency and rate limits."""
        now = time.time() if time_source is None else time_source

        with self._lock:
            quota = self._quotas.get(
                tenant_id,
                TenantQuota(
                    tenant_id=tenant_id,
                    max_concurrent=self._default_quota.max_concurrent,
                    rate_limit_per_second=self._default_quota.rate_limit_per_second,
                    burst_capacity=self._default_quota.burst_capacity,
                ),
            )

            if tenant_id not in self._usages:
                self._usages[tenant_id] = TenantUsage(
                    tenant_id=tenant_id,
                    available_tokens=quota.burst_capacity,
                    last_token_refill=now,
                )

            usage = self._usages[tenant_id]

            # 1. Check concurrency ceiling
            if usage.active_concurrent >= quota.max_concurrent:
                return False

            # 2. Refill token bucket based on elapsed time
            delta = max(0.0, now - usage.last_token_refill)
            refill = delta * quota.rate_limit_per_second
            usage.available_tokens = min(quota.burst_capacity, usage.available_tokens + refill)
            usage.last_token_refill = now

            # 3. Check rate limit tokens
            if usage.available_tokens < tokens:
                return False

            # Consume token and occupy concurrency slot
            usage.available_tokens -= tokens
            usage.active_concurrent += 1
            return True

    def release(self, tenant_id: str) -> None:
        """Release a concurrency slot upon task termination."""
        with self._lock:
            if tenant_id in self._usages:
                self._usages[tenant_id].active_concurrent = max(
                    0, self._usages[tenant_id].active_concurrent - 1
                )

    def wrap_tenant_task(
        self,
        tenant_id: str,
        runner: Callable[[Task], TaskResult],
        raise_on_quota: bool = False,
    ) -> Callable[[Task], TaskResult]:
        """Wrap a task runner with tenant quota verification."""

        def wrapped(task: Task) -> TaskResult:
            if not self.acquire(tenant_id):
                msg = f"Tenant '{tenant_id}' quota exceeded (concurrency or rate limit)"
                if raise_on_quota:
                    raise TenantQuotaExceededError(msg)
                return TaskResult(ok=False, error=msg)

            try:
                return runner(task)
            finally:
                self.release(tenant_id)

        return wrapped

    def create_hooks(
        self,
        tenant_resolver: Callable[[Task], str],
    ) -> Hooks:
        """Create runner Hooks that automatically release quota slots on task completion."""

        def on_task_succeeded(task: Task) -> None:
            tid = tenant_resolver(task)
            self.release(tid)

        def on_task_failed(task: Task) -> None:
            tid = tenant_resolver(task)
            self.release(tid)

        return Hooks(
            on_task_succeeded=on_task_succeeded,
            on_task_failed=on_task_failed,
        )
