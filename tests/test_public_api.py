"""Public API freeze tests.

Asserts that __all__ contains exactly the approved public API symbols and snapshots
their signatures, dataclass fields, and enum values.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

import orchestration_engine as oe

EXPECTED_PUBLIC_API = {
    # Original 11 symbols
    "Task",
    "Workflow",
    "RetryPolicy",
    "TaskState",
    "WorkflowStatus",
    "run_workflow",
    "run_workflow_from_file",
    "load_workflow_from_json",
    "get_workflow_status",
    "get_workflow_history",
    "get_connection",
    # Stage 2 additions
    "OrchestrationError",
    "WorkflowDefinitionError",
    "WorkflowValidationError",
    "PersistenceError",
    "__version__",
    # Stage 3 additions
    "resume_run",
    "get_run_status",
    "get_run_history",
    "list_runs",
    # Stage 5 additions
    "TaskResult",
    "Hooks",
    "WorkflowBuilder",
    "workflow_to_dict",
    "load_workflow_from_yaml",
    # Async addition
    "run_workflow_async",
    # Decorator additions
    "task",
    "workflow",
    # Caching & Rate Limiting additions
    "TaskCache",
    "TokenBucketRateLimiter",
    # Enterprise & Observability additions
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
    "run_workflow_multiprocess",
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
}


def test_public_api_symbols() -> None:
    """Assert __all__ exactly matches the approved symbol set."""
    assert set(oe.__all__) == EXPECTED_PUBLIC_API


def test_public_dataclass_fields() -> None:
    """Snapshot dataclass fields for all public dataclasses."""
    task_fields = [f.name for f in dataclasses.fields(oe.Task)]
    assert task_fields == [
        "task_id",
        "workflow_id",
        "name",
        "description",
        "dependencies",
        "state",
        "retry_policy",
        "attempt_count",
        "next_retry_at",
        "timeout_seconds",
        "last_error",
        "_run_id",
        "inputs",
    ]

    wf_fields = [f.name for f in dataclasses.fields(oe.Workflow)]
    assert wf_fields == [
        "workflow_id",
        "name",
        "description",
        "tasks",
        "default_timeout_seconds",
    ]

    retry_fields = [f.name for f in dataclasses.fields(oe.RetryPolicy)]
    assert retry_fields == ["max_attempts", "delay_seconds"]

    result_fields = [f.name for f in dataclasses.fields(oe.TaskResult)]
    assert result_fields == ["ok", "output", "error"]
    assert dataclasses.is_dataclass(oe.TaskResult)
    # TaskResult is frozen
    tr = oe.TaskResult(ok=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        tr.ok = False  # type: ignore[misc]

    hooks_fields = [f.name for f in dataclasses.fields(oe.Hooks)]
    assert hooks_fields == [
        "on_task_start",
        "on_task_succeeded",
        "on_task_failed",
        "on_task_retry",
        "on_workflow_done",
    ]

    sub_wf_fields = [f.name for f in dataclasses.fields(oe.SubWorkflowResult)]
    assert sub_wf_fields == ["child_run_id", "status", "outputs", "error"]

    inc_fields = [f.name for f in dataclasses.fields(oe.IncrementalRunResult)]
    assert inc_fields == ["skipped_task_ids", "executed_task_ids"]

    adapt_fields = [f.name for f in dataclasses.fields(oe.AdaptiveConcurrencyPolicy)]
    assert adapt_fields == [
        "min_concurrency",
        "max_concurrency",
        "initial_concurrency",
        "backoff_factor",
        "step_increase",
        "latency_threshold_seconds",
        "max_cpu_load",
    ]

    blob_fields = [f.name for f in dataclasses.fields(oe.BlobReference)]
    assert blob_fields == ["blob_hash", "uncompressed_bytes", "compressed_bytes", "path"]

    cdc_run_fields = [f.name for f in dataclasses.fields(oe.CDCRun)]
    assert cdc_run_fields == [
        "run_id",
        "workflow_id",
        "started_at",
        "finished_at",
        "status",
        "definition_json",
    ]

    cdc_event_fields = [f.name for f in dataclasses.fields(oe.CDCEvent)]
    assert cdc_event_fields == [
        "event_id",
        "workflow_id",
        "task_id",
        "old_state",
        "new_state",
        "timestamp",
        "attempt_count",
        "run_id",
    ]

    cdc_out_fields = [f.name for f in dataclasses.fields(oe.CDCOutput)]
    assert cdc_out_fields == ["run_id", "task_id", "output_json", "error"]

    cdc_batch_fields = [f.name for f in dataclasses.fields(oe.CDCBatch)]
    assert cdc_batch_fields == ["last_event_id", "runs", "events", "outputs"]

    worker_fields = [f.name for f in dataclasses.fields(oe.WorkerNodeInfo)]
    assert worker_fields == [
        "worker_id",
        "capacity",
        "active_tasks",
        "last_heartbeat",
        "status",
        "host",
        "port",
    ]

    backfill_win_fields = [f.name for f in dataclasses.fields(oe.BackfillWindow)]
    assert backfill_win_fields == [
        "window_id",
        "start_time",
        "end_time",
        "jitter_seconds",
        "status",
        "run_id",
    ]

    backfill_plan_fields = [f.name for f in dataclasses.fields(oe.BackfillPlan)]
    assert backfill_plan_fields == ["workflow_id", "windows", "catchup_policy"]

    quota_fields = [f.name for f in dataclasses.fields(oe.TenantQuota)]
    assert quota_fields == [
        "tenant_id",
        "max_concurrent",
        "rate_limit_per_second",
        "burst_capacity",
    ]

    usage_fields = [f.name for f in dataclasses.fields(oe.TenantUsage)]
    assert usage_fields == [
        "tenant_id",
        "active_concurrent",
        "available_tokens",
        "last_token_refill",
    ]

    ctx_fields = [f.name for f in dataclasses.fields(oe.TaskExecutionContext)]
    assert ctx_fields == [
        "task",
        "run_id",
        "metadata",
        "start_time",
        "end_time",
        "attempt",
    ]

    incident_fields = [f.name for f in dataclasses.fields(oe.ZombieTaskIncident)]
    assert incident_fields == [
        "incident_id",
        "run_id",
        "task_id",
        "elapsed_seconds",
        "remedy_applied",
        "reason",
        "created_at",
    ]

    policy_fields = [f.name for f in dataclasses.fields(oe.SupervisorPolicy)]
    assert policy_fields == [
        "stuck_timeout_seconds",
        "default_remedy",
        "max_auto_retries",
    ]


def test_public_enum_values() -> None:
    """Snapshot enum values."""
    assert {s.value for s in oe.TaskState} == {
        "pending",
        "ready",
        "running",
        "succeeded",
        "retry_wait",
        "failed",
        "cancelled",
    }

    assert {s.value for s in oe.WorkflowStatus} == {
        "running",
        "succeeded",
        "failed",
    }

    assert {s.value for s in oe.CatchupPolicy} == {
        "ALL",
        "LATEST_ONLY",
        "SLIDING_WINDOW",
    }

    assert {s.value for s in oe.AutoRemedy} == {
        "RETRY",
        "ABORT_RUN",
        "NOTIFY",
    }


def test_public_callable_signatures() -> None:
    """Snapshot signatures of all public functions and classes."""
    # run_workflow
    sig = inspect.signature(oe.run_workflow)
    param_names = list(sig.parameters.keys())
    assert param_names == [
        "workflow",
        "task_states",
        "time_source",
        "task_runner",
        "conn",
        "sleep",
        "run_id",
        "max_concurrency",
        "executor",
        "hooks",
    ]
    assert sig.parameters["max_concurrency"].default == 1
    assert sig.parameters["executor"].default == "thread"

    # resume_run
    sig = inspect.signature(oe.resume_run)
    assert list(sig.parameters.keys()) == [
        "conn",
        "run_id",
        "task_runner",
        "time_source",
        "sleep",
        "max_concurrency",
        "executor",
        "hooks",
    ]

    # run_workflow_from_file
    sig = inspect.signature(oe.run_workflow_from_file)
    assert list(sig.parameters.keys()) == [
        "path",
        "task_runner",
        "time_source",
        "conn",
        "run_id",
        "max_concurrency",
        "executor",
        "hooks",
    ]

    # get_connection
    sig = inspect.signature(oe.get_connection)
    assert list(sig.parameters.keys()) == ["path"]
    assert sig.parameters["path"].default is None

    # get_run_status
    sig = inspect.signature(oe.get_run_status)
    assert list(sig.parameters.keys()) == ["conn", "run_id"]

    # get_run_history
    sig = inspect.signature(oe.get_run_history)
    assert list(sig.parameters.keys()) == ["conn", "run_id"]

    # list_runs
    sig = inspect.signature(oe.list_runs)
    assert list(sig.parameters.keys()) == ["conn", "workflow_id"]
    assert sig.parameters["workflow_id"].default is None

    # workflow_to_dict
    sig = inspect.signature(oe.workflow_to_dict)
    assert list(sig.parameters.keys()) == ["workflow"]

    # load_workflow_from_json
    sig = inspect.signature(oe.load_workflow_from_json)
    assert list(sig.parameters.keys()) == ["json_data", "collect_errors"]
    assert sig.parameters["collect_errors"].default is False

    # load_workflow_from_yaml
    sig = inspect.signature(oe.load_workflow_from_yaml)
    assert list(sig.parameters.keys()) == ["source", "collect_errors"]

    # run_saga
    sig = inspect.signature(oe.run_saga)
    assert "workflow" in sig.parameters
    assert "task_runner" in sig.parameters
    assert "compensators" in sig.parameters

    # generate_execution_plan
    sig = inspect.signature(oe.generate_execution_plan)
    assert list(sig.parameters.keys()) == ["workflow"]

    # acquire_lease
    sig = inspect.signature(oe.acquire_lease)
    assert "db_path" in sig.parameters
    assert "resource_id" in sig.parameters
    assert "owner_id" in sig.parameters

    # run_workflow_async
    sig = inspect.signature(oe.run_workflow_async)
    assert "workflow" in sig.parameters
    assert "task_runner" in sig.parameters
    assert sig.parameters["max_concurrency"].default == 100

    # run_workflow_multiprocess
    sig = inspect.signature(oe.run_workflow_multiprocess)
    assert "workflow" in sig.parameters
    assert "task_runner" in sig.parameters

    # map_tasks
    sig = inspect.signature(oe.map_tasks)
    assert "base_task_id" in sig.parameters
    assert "items" in sig.parameters

    # fan_in_task
    sig = inspect.signature(oe.fan_in_task)
    assert "task_id" in sig.parameters
    assert "mapped_tasks" in sig.parameters

    # force_complete_task
    sig = inspect.signature(oe.force_complete_task)
    assert "conn" in sig.parameters
    assert "run_id" in sig.parameters
    assert "task_id" in sig.parameters


def test_exception_hierarchy() -> None:
    """Verify exception inheritance."""
    assert issubclass(oe.WorkflowDefinitionError, oe.OrchestrationError)
    assert issubclass(oe.WorkflowValidationError, oe.OrchestrationError)
    assert issubclass(oe.PersistenceError, oe.OrchestrationError)
    assert issubclass(oe.TenantQuotaExceededError, oe.OrchestrationError)
    assert issubclass(oe.OrchestrationError, Exception)
    assert issubclass(oe.SignalTimeoutError, TimeoutError)
