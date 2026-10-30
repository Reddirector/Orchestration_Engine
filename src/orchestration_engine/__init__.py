import importlib.metadata
import logging

from .async_runner import run_workflow_async
from .branching import BranchDecision, apply_branch_decision, evaluate_branch
from .builder import WorkflowBuilder, workflow_to_dict
from .caching import TaskCache
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from .dead_letter import DeadLetterMessage, DeadLetterQueue, create_dlq_hook
from .decorators import task, workflow
from .distributed import CoordinatorServer, WorkerAgent
from .dynamic_map import fan_in_task, map_tasks
from .errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowDefinitionError,
    WorkflowValidationError,
)
from .lease import TaskLease, acquire_lease, get_lease, release_lease, renew_lease
from .loader import (
    load_workflow_from_json,
    load_workflow_from_yaml,
    run_workflow_from_file,
)
from .models import Hooks, RetryPolicy, Task, TaskResult, TaskState, Workflow, WorkflowStatus
from .persistence import (
    force_complete_task,
    get_connection,
    get_run_history,
    get_workflow_history,
    list_runs,
)
from .plan import ExecutionPlan, ExecutionStage, generate_execution_plan
from .priority import PriorityTaskQueue, TaskPriority
from .process_runner import run_workflow_multiprocess
from .rate_limiter import TokenBucketRateLimiter
from .runner import resume_run, run_workflow
from .sagas import SagaResult, SagaStatus, run_saga
from .sandbox import ResourceLimits, sandboxed, sandboxed_run
from .scheduler import CronSchedule, IntervalSchedule, WorkflowScheduler
from .signals import SignalBroker, SignalTimeoutError, default_signal_broker
from .state_graph import (
    END,
    START,
    CompiledStateGraph,
    StateCheckpointer,
    StateGraph,
    StateGraphResult,
)
from .status import get_run_status, get_workflow_status
from .streaming import StreamPipe, run_streaming_pipeline
from .tracing import Span, TraceExporter
from .watermark import Watermark, WatermarkStore

logging.getLogger("orchestration_engine").addHandler(logging.NullHandler())

try:
    __version__ = importlib.metadata.version("orchestration-engine")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.9.0"

__all__ = [
    "__version__",
    "Task",
    "TaskResult",
    "Workflow",
    "RetryPolicy",
    "TaskState",
    "WorkflowStatus",
    "Hooks",
    "WorkflowBuilder",
    "workflow_to_dict",
    "run_workflow",
    "run_workflow_async",
    "run_workflow_multiprocess",
    "run_workflow_from_file",
    "resume_run",
    "load_workflow_from_json",
    "load_workflow_from_yaml",
    "get_workflow_status",
    "get_run_status",
    "get_workflow_history",
    "get_run_history",
    "list_runs",
    "get_connection",
    "OrchestrationError",
    "WorkflowDefinitionError",
    "WorkflowValidationError",
    "PersistenceError",
    "task",
    "workflow",
    "TaskCache",
    "TokenBucketRateLimiter",
    "CronSchedule",
    "IntervalSchedule",
    "WorkflowScheduler",
    "map_tasks",
    "fan_in_task",
    "SignalBroker",
    "default_signal_broker",
    "SignalTimeoutError",
    "TraceExporter",
    "Span",
    "force_complete_task",
    # Enterprise Work Fields
    "run_saga",
    "SagaResult",
    "SagaStatus",
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenError",
    "DeadLetterQueue",
    "DeadLetterMessage",
    "create_dlq_hook",
    "TaskLease",
    "acquire_lease",
    "renew_lease",
    "release_lease",
    "get_lease",
    "evaluate_branch",
    "apply_branch_decision",
    "BranchDecision",
    "WatermarkStore",
    "Watermark",
    "generate_execution_plan",
    "ExecutionPlan",
    "ExecutionStage",
    # Next-Gen Pillars
    "StateGraph",
    "CompiledStateGraph",
    "StateGraphResult",
    "StateCheckpointer",
    "START",
    "END",
    "StreamPipe",
    "run_streaming_pipeline",
    "PriorityTaskQueue",
    "TaskPriority",
    "sandboxed",
    "sandboxed_run",
    "ResourceLimits",
    "CoordinatorServer",
    "WorkerAgent",
]
