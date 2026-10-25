from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskState(StrEnum):
    """Lifecycle states a single Task can be in."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RetryPolicy:
    """
    Retry configuration for a single Task.

    Attributes:
        max_attempts: Total number of attempts allowed, including the first.
        delay_seconds: Base delay before retries, in seconds.
    """
    max_attempts: int
    delay_seconds: float


@dataclass
class Task:
    """
    A single unit of work within a Workflow.

    Attributes:
        task_id: Unique identifier within the workflow.
        workflow_id: ID of the Workflow this task belongs to.
        name: Human-readable name.
        description: Human-readable description.
        dependencies: task_ids that must reach TaskState.SUCCEEDED before this task becomes ready.
        state: Current lifecycle state. Mutated in place as the workflow runs.
        retry_policy: Retry behavior for this task.
        attempt_count: Number of attempts made so far.
        next_retry_at: Timestamp after which a retry may run, if in RETRY_WAIT.
        timeout_seconds: Seconds allowed before the task is considered timed out and failed.
            Defaults to 30.0 (None disables timeout).
        last_error: Error message from the last failed attempt, if any.
    """
    task_id: str
    workflow_id: str
    name: str
    description: str
    dependencies: list[str]
    state: TaskState
    retry_policy: RetryPolicy
    attempt_count: int = 0
    next_retry_at: float | None = None
    timeout_seconds: float | None = 30.0
    last_error: str | None = None
    _run_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    """
    Result returned by a task runner callable.

    Attributes:
        ok: Whether the task succeeded.
        output: Output data produced by the task (must be JSON-serializable).
        error: Optional error message if the task failed.
    """
    ok: bool
    output: Any = None
    error: str | None = None


@dataclass
class Workflow:
    """
    A named collection of Tasks with dependency relationships between them.

    Attributes:
        workflow_id: Unique identifier for this workflow.
        name: Human-readable name.
        description: Human-readable description.
        tasks: The tasks that make up this workflow.
        default_timeout_seconds: Optional default timeout in seconds for tasks in this workflow.
    """
    workflow_id: str
    name: str
    description: str
    tasks: list[Task]
    default_timeout_seconds: float | None = None


class WorkflowStatus(StrEnum):
    """Overall status of a Workflow, derived from its tasks' states."""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
