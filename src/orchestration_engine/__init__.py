import importlib.metadata
import logging

from .adaptive import AdaptiveConcurrencyController, AdaptiveConcurrencyPolicy
from .async_runner import run_workflow_async
from .backfill import (
    BackfillExecutor,
    BackfillPlan,
    BackfillWindow,
    CatchupPolicy,
    generate_backfill_plan,
)
from .blackboard import WorkflowBlackboard
from .blobs import BLOB_MARKER_KEY, BlobReference, BlobStore
from .branching import BranchDecision, apply_branch_decision, evaluate_branch
from .builder import WorkflowBuilder, workflow_to_dict
from .caching import TaskCache
from .chaos import ChaosFaultError, ChaosInjector, ChaosPolicy, with_chaos
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from .contracts import ContractValidationError, DataContract, Field, enforce_contract
from .dead_letter import DeadLetterMessage, DeadLetterQueue, create_dlq_hook
from .decorators import task, workflow
from .distributed import CoordinatorServer, WorkerAgent
from .durable_sleep import (
    DURABLE_SLEEP_KEY,
    DurableTimer,
    TimerStatus,
    TimerStore,
    create_sleep_marker,
)
from .dynamic_map import fan_in_task, map_tasks
from .errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowDefinitionError,
    WorkflowValidationError,
)
from .events import Event, EventBus, EventSubscription, WebhookServer
from .idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyStore,
    idempotent,
)
from .incremental import (
    IncrementalRunResult,
    IncrementalStore,
    compute_task_hash,
    wrap_incremental,
)
from .lease import TaskLease, acquire_lease, get_lease, release_lease, renew_lease
from .loader import (
    load_workflow_from_json,
    load_workflow_from_yaml,
    run_workflow_from_file,
)
from .middleware import (
    Middleware,
    MiddlewarePipeline,
    TaskExecutionContext,
    audit_logging_middleware,
    execution_timer_middleware,
    secret_masking_middleware,
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
from .quotas import (
    TenantQuota,
    TenantQuotaExceededError,
    TenantQuotaManager,
    TenantUsage,
)
from .rate_limiter import TokenBucketRateLimiter
from .replay import WorkflowReplaySnapshot, fork_run_from_task, time_travel_inspect
from .replication import (
    CDCBatch,
    CDCEvent,
    CDCOutput,
    CDCReplicationSource,
    CDCReplicationTarget,
    CDCRun,
    ReplicationClient,
    ReplicationServer,
)
from .retention import compact_event_log, export_cold_archive, vacuum_database
from .runner import resume_run, run_workflow
from .sagas import SagaResult, SagaStatus, run_saga
from .sandbox import ResourceLimits, sandboxed, sandboxed_run
from .scheduler import CronSchedule, IntervalSchedule, WorkflowScheduler
from .signals import SignalBroker, SignalTimeoutError, default_signal_broker
from .sla import SLABreachRecord, SLAMonitor, SLAPolicy
from .state_graph import (
    END,
    START,
    CompiledStateGraph,
    StateCheckpointer,
    StateGraph,
    StateGraphResult,
)
from .status import get_run_status, get_workflow_status
from .stealing import (
    WorkerNodeInfo,
    WorkStealingRegistry,
)
from .streaming import StreamPipe, run_streaming_pipeline
from .subworkflows import (
    SubWorkflowResult,
    execute_subworkflow,
    get_subworkflow_tree,
    make_subworkflow_runner,
)
from .supervisor import (
    AutoRemedy,
    SupervisorPolicy,
    WorkflowSupervisor,
    ZombieTaskIncident,
)
from .tracing import Span, TraceExporter
from .versioning import (
    MigrationPolicy,
    VersionDiff,
    WorkflowVersionRegistry,
    compare_workflows,
    compute_workflow_hash,
)
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
    # Upscaled Resilience & Developer Primitives
    "DURABLE_SLEEP_KEY",
    "TimerStatus",
    "DurableTimer",
    "TimerStore",
    "create_sleep_marker",
    "ContractValidationError",
    "Field",
    "DataContract",
    "enforce_contract",
    "ChaosFaultError",
    "ChaosPolicy",
    "ChaosInjector",
    "with_chaos",
    "WorkflowReplaySnapshot",
    "time_travel_inspect",
    "fork_run_from_task",
    "MigrationPolicy",
    "VersionDiff",
    "WorkflowVersionRegistry",
    "compute_workflow_hash",
    "compare_workflows",
    # Enterprise Platform Expansion
    "IdempotencyStatus",
    "IdempotencyConflictError",
    "IdempotencyRecord",
    "IdempotencyStore",
    "idempotent",
    "Event",
    "EventSubscription",
    "EventBus",
    "WebhookServer",
    "WorkflowBlackboard",
    "SLAPolicy",
    "SLABreachRecord",
    "SLAMonitor",
    "compact_event_log",
    "export_cold_archive",
    "vacuum_database",
    # Advanced Architectural Upscale
    "SubWorkflowResult",
    "execute_subworkflow",
    "make_subworkflow_runner",
    "get_subworkflow_tree",
    "compute_task_hash",
    "IncrementalStore",
    "IncrementalRunResult",
    "wrap_incremental",
    "AdaptiveConcurrencyPolicy",
    "AdaptiveConcurrencyController",
    "BLOB_MARKER_KEY",
    "BlobReference",
    "BlobStore",
    "CDCRun",
    "CDCEvent",
    "CDCOutput",
    "CDCBatch",
    "CDCReplicationSource",
    "CDCReplicationTarget",
    "ReplicationServer",
    "ReplicationClient",
    # Distributed Stealing & Reclamation
    "WorkerNodeInfo",
    "WorkStealingRegistry",
    # Historical Backfill & Catchup
    "CatchupPolicy",
    "BackfillWindow",
    "BackfillPlan",
    "generate_backfill_plan",
    "BackfillExecutor",
    # Multi-Tenant Quotas
    "TenantQuotaExceededError",
    "TenantQuota",
    "TenantUsage",
    "TenantQuotaManager",
    # Task Middleware Pipeline
    "TaskExecutionContext",
    "Middleware",
    "MiddlewarePipeline",
    "secret_masking_middleware",
    "execution_timer_middleware",
    "audit_logging_middleware",
    # Self-Healing Supervisor
    "AutoRemedy",
    "ZombieTaskIncident",
    "SupervisorPolicy",
    "WorkflowSupervisor",
]
