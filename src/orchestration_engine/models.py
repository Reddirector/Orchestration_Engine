from dataclasses import dataclass
from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RetryPolicy:
    max_attempts: int
    delay_seconds: int


@dataclass
class Task:
    task_id: str
    name: str
    description: str
    dependencies: list[str]
    state: TaskState
    retry_policy: RetryPolicy
    attempt_count: int = 0
    next_retry_at: float | None = None
    timeout_seconds: int = 1


@dataclass
class Workflow:
    workflow_id: str
    name: str
    description: str
    tasks: list[Task]


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
