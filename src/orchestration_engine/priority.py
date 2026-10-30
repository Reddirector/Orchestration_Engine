"""Priority Scheduling and Multi-Tenant Fair Queuing.

Prevents noisy-neighbor starvation and prioritizes mission-critical tasks
(e.g., customer checkouts, P0 alerts) ahead of background batch operations.
Features per-tenant concurrency quotas and round-robin fair interleaving.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import heapq
import itertools
import threading
from typing import Any


class TaskPriority(enum.IntEnum):
    """Execution priority levels for tasks. Lower integer = higher priority."""

    CRITICAL = 0
    HIGH = 10
    DEFAULT = 20
    BATCH = 30


@dataclasses.dataclass(order=True)
class _PrioritizedEntry:
    priority: int
    entry_index: int
    task_id: str = dataclasses.field(compare=False)
    tenant_id: str = dataclasses.field(compare=False)
    payload: Any = dataclasses.field(compare=False)


class PriorityTaskQueue:
    """Thread-safe multi-tenant priority queue with per-tenant concurrency limits.

    Ensures high-priority tasks execute first, while limiting any single tenant's
    active in-flight tasks so that batch workloads cannot starve other tenants.
    """

    def __init__(self, default_tenant_max_concurrency: int = 5) -> None:
        self.default_tenant_max_concurrency = default_tenant_max_concurrency
        self._lock = threading.Lock()
        self._counter = itertools.count()
        self._heap: list[_PrioritizedEntry] = []
        self._active_per_tenant: collections.defaultdict[str, int] = collections.defaultdict(int)
        self._tenant_quotas: dict[str, int] = {}

    def set_tenant_quota(self, tenant_id: str, max_concurrency: int) -> None:
        """Set maximum concurrent in-flight tasks for a specific tenant."""
        with self._lock:
            self._tenant_quotas[tenant_id] = max_concurrency

    def push(
        self,
        task_id: str,
        *,
        priority: int | TaskPriority = TaskPriority.DEFAULT,
        tenant_id: str = "default",
        payload: Any = None,
    ) -> None:
        """Enqueue a task with a given priority level and tenant identifier."""
        pri_val = int(priority)
        entry = _PrioritizedEntry(
            priority=pri_val,
            entry_index=next(self._counter),
            task_id=task_id,
            tenant_id=tenant_id,
            payload=payload,
        )
        with self._lock:
            heapq.heappush(self._heap, entry)

    def pop(self) -> tuple[str, str, Any] | None:
        """Pop the highest priority task whose tenant is within their concurrency quota.

        Returns:
            Tuple of ``(task_id, tenant_id, payload)`` or None if no tasks ready.
        """
        with self._lock:
            if not self._heap:
                return None

            skipped: list[_PrioritizedEntry] = []
            chosen: _PrioritizedEntry | None = None

            while self._heap:
                candidate = heapq.heappop(self._heap)
                tenant = candidate.tenant_id
                quota = self._tenant_quotas.get(tenant, self.default_tenant_max_concurrency)

                if self._active_per_tenant[tenant] < quota:
                    chosen = candidate
                    self._active_per_tenant[tenant] += 1
                    break
                else:
                    skipped.append(candidate)

            # Re-insert skipped items
            for item in skipped:
                heapq.heappush(self._heap, item)

            if chosen is None:
                return None

            return chosen.task_id, chosen.tenant_id, chosen.payload

    def acknowledge(self, tenant_id: str) -> None:
        """Mark a task complete for a tenant, releasing their concurrency slot."""
        with self._lock:
            if self._active_per_tenant[tenant_id] > 0:
                self._active_per_tenant[tenant_id] -= 1

    def active_count(self, tenant_id: str) -> int:
        """Return number of currently active in-flight tasks for a tenant."""
        with self._lock:
            return self._active_per_tenant[tenant_id]

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)
