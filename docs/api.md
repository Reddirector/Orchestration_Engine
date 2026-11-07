# API Reference

Complete reference for all public classes, functions, enums, and exceptions exported by `orchestration_engine`. The engine provides **116 frozen public API exports** under strict semantic versioning, implemented with **zero external runtime dependencies** (Python 3.10+ standard library).

---

## 1. Models & Data Structures

### `Task`
Dataclass representing a discrete unit of work within a workflow.
```python
@dataclass
class Task:
    task_id: str
    name: str
    dependencies: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_seconds: float | None = 30.0
    state: TaskState = TaskState.PENDING
    attempt_count: int = 0
    next_retry_at: float | None = None
    last_error: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
```

### `Workflow`
Dataclass representing a directed acyclic graph of tasks.
```python
@dataclass
class Workflow:
    workflow_id: str
    name: str
    tasks: list[Task]
    description: str = ""
    default_timeout_seconds: float | None = None
```

### `RetryPolicy`
Policy defining retry attempts and exponential backoff timing.
```python
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    delay_seconds: float = 1.0
```

### `TaskResult`
Frozen dataclass returned by task runners to provide structured output or error messages.
```python
@dataclass(frozen=True)
class TaskResult:
    ok: bool
    output: Any = None
    error: str | None = None
```

### `Hooks`
Dataclass defining non-blocking lifecycle callbacks.
```python
@dataclass
class Hooks:
    on_task_start: Callable[[Task], None] | None = None
    on_task_succeeded: Callable[[Task], None] | None = None
    on_task_failed: Callable[[Task], None] | None = None
    on_task_retry: Callable[[Task], None] | None = None
    on_workflow_done: Callable[[Workflow, WorkflowStatus], None] | None = None
```

### `TaskState`
Enumeration of possible task lifecycle states:
- `TaskState.PENDING`: `"pending"`
- `TaskState.READY`: `"ready"`
- `TaskState.RUNNING`: `"running"`
- `TaskState.SUCCEEDED`: `"succeeded"`
- `TaskState.RETRY_WAIT`: `"retry_wait"`
- `TaskState.FAILED`: `"failed"`
- `TaskState.CANCELLED`: `"cancelled"`

### `WorkflowStatus`
Enumeration of overall workflow execution status:
- `WorkflowStatus.RUNNING`: `"running"`
- `WorkflowStatus.SUCCEEDED`: `"succeeded"`
- `WorkflowStatus.FAILED`: `"failed"`
- `WorkflowStatus.CANCELLED`: `"cancelled"`

---

## 2. Execution Coordinators

### `run_workflow`
```python
def run_workflow(
    workflow: Workflow,
    task_states: dict[str, TaskState],
    time_source: Callable[[], float],
    task_runner: Callable[[Task], bool | TaskResult],
    conn: sqlite3.Connection,
    sleep: Callable[[float], None] = time.sleep,
    *,
    run_id: str | None = None,
    max_concurrency: int = 1,
    executor: Literal["thread", "process", "_inline"] = "thread",
    hooks: Hooks | None = None,
) -> str:
```
Executes a workflow to completion synchronously and returns the executed `run_id`.

### `run_workflow_async`
```python
async def run_workflow_async(
    workflow: Workflow,
    task_runner: Callable[[Task], Awaitable[bool | TaskResult] | bool | TaskResult],
    conn: sqlite3.Connection,
    *,
    run_id: str | None = None,
    max_concurrency: int = 10,
    hooks: Hooks | None = None,
) -> WorkflowStatus:
```
Native high-throughput `asyncio` DAG execution coordinator capable of coordinating concurrent `async def` and synchronous tasks with non-blocking timeouts (`asyncio.wait_for`).

### `run_workflow_multiprocess`
```python
def run_workflow_multiprocess(
    workflow: Workflow,
    task_runner: Callable[[Task], bool | TaskResult],
    conn: sqlite3.Connection,
    *,
    max_workers: int | None = None,
) -> str:
```
High-throughput execution across separate Python OS child processes, bypassing the GIL for CPU-bound computation and vector embeddings.

### `run_workflow_from_file`
```python
def run_workflow_from_file(
    path: str,
    task_runner: Callable[[Task], bool | TaskResult],
    time_source: Callable[[], float],
    conn: sqlite3.Connection,
    *,
    run_id: str | None = None,
    max_concurrency: int = 1,
    executor: Literal["thread", "process", "_inline"] = "thread",
    hooks: Hooks | None = None,
) -> WorkflowStatus:
```
Loads a workflow definition from JSON or YAML and executes it end-to-end.

### `resume_run`
```python
def resume_run(
    conn: sqlite3.Connection,
    run_id: str,
    task_runner: Callable[[Task], bool | TaskResult],
    time_source: Callable[[], float] = time.time,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_concurrency: int = 1,
    executor: Literal["thread", "process", "_inline"] = "thread",
    hooks: Hooks | None = None,
) -> WorkflowStatus:
```
Resumes an interrupted or partially-failed workflow run from SQLite state without re-running succeeded tasks.

---

## 3. Builders & Functional Decorators

### `WorkflowBuilder`
Fluent builder for defining validated workflows with topology verification:
- `WorkflowBuilder(workflow_id: str, name: str)`
- `.description(desc: str) -> WorkflowBuilder`
- `.default_timeout(seconds: float | None) -> WorkflowBuilder`
- `.task(task_id: str, name: str, dependencies: list[str] = ..., retry_policy: RetryPolicy = ..., timeout_seconds: float | None = ...) -> WorkflowBuilder`
- `.build() -> Workflow`

### `@task` & `@workflow` Decorators
Author DAGs directly from Python functions:
```python
from orchestration_engine import task, workflow

@task(retries=3, delay=1.0)
def fetch_data() -> dict:
    return {"raw": [1, 2, 3]}

@task
def process_data(fetch_data: dict) -> int:
    return sum(fetch_data["raw"])

@workflow
def etl_pipeline():
    raw = fetch_data()
    return process_data(raw)

# Execute:
result = etl_pipeline.run()
# Or async:
# result = await etl_pipeline.run_async()
```

### Serialization & Deserialization
- `workflow_to_dict(workflow: Workflow) -> dict[str, Any]`
- `load_workflow_from_json(json_data: dict[str, Any], *, collect_errors: bool = False) -> Workflow`
- `load_workflow_from_yaml(source: str | os.PathLike[str] | Any, *, collect_errors: bool = False) -> Workflow`

---

## 4. State Introspection & Persistence

- `get_connection(db_path: str = ":memory:") -> sqlite3.Connection`: Initializes an SQLite connection with WAL mode and schema migrations.
- `get_run_status(conn: sqlite3.Connection, run_id: str) -> WorkflowStatus`: Queries the current status of a run directly from database events.
- `get_workflow_status(workflow: Workflow) -> WorkflowStatus`: Computes in-memory workflow status.
- `get_run_history(conn: sqlite3.Connection, run_id: str) -> list[tuple[Any, ...]]`: Returns ordered event tuples for a specific run.
- `get_workflow_history(conn: sqlite3.Connection, workflow_id: str) -> list[tuple[Any, ...]]`: Returns historical events for a workflow.
- `list_runs(conn: sqlite3.Connection, workflow_id: str | None = None) -> list[tuple[Any, ...]]`: Lists recorded runs.
- `force_complete_task(conn: sqlite3.Connection, run_id: str, task_id: str, output: Any = None) -> None`: Overrides a failed or stalled task, unblocking downstream dependents with synthetic fallback output.

---

## 5. Resilience, SRE & Observability

### Distributed Sagas
```python
def run_saga(
    workflow: Workflow,
    forward_runner: Callable[[Task], bool | TaskResult],
    compensating_runner: Callable[[Task], None],
    conn: sqlite3.Connection,
) -> SagaResult:
```
Executes backward compensating transactions in reverse topological order if any step fails.

### Resilient Circuit Breaker
- `CircuitBreaker(name: str, conn: sqlite3.Connection, failure_threshold: int = 5, recovery_timeout: float = 30.0)`
- `CircuitState`: `CLOSED`, `OPEN`, `HALF_OPEN`
- `CircuitBreakerOpenError`: Raised on calls while open.
- `@cb.protect`: Decorator wrapping API/microservice calls.

### Dead Letter Queue (DLQ)
- `DeadLetterQueue(conn: sqlite3.Connection)`: Persistent storage for failed tasks.
- `DeadLetterMessage`: Dataclass capturing task failure metadata, parameters, and stack traces.
- `create_dlq_hook(dlq: DeadLetterQueue) -> Hooks`: Non-blocking lifecycle hook capturing task failures into DLQ.

### Result Caching & Rate Limiting
- `TaskCache(conn: sqlite3.Connection, default_ttl_seconds: float | None = None)`: SHA-256 input memoization preventing redundant executions.
- `TokenBucketRateLimiter(rate: float, capacity: float)`: Thread-safe and async-safe token bucket rate limiter with `@limiter.limit` and `@limiter.limit_async`.

### Distributed Advisory Leases
- `acquire_lease(conn, resource_name: str, worker_id: str, ttl_seconds: float = 30.0) -> TaskLease | None`
- `renew_lease(conn, lease: TaskLease, extend_seconds: float = 30.0) -> bool`
- `release_lease(conn, lease: TaskLease) -> bool`
- `get_lease(conn, resource_name: str) -> TaskLease | None`

### Tracing & OpenTelemetry
- `TraceExporter(conn: sqlite3.Connection)`: Exports execution spans to Chrome Trace (Perfetto UI compatible) and W3C OpenTelemetry JSON.
- `Span`: Dataclass holding start/end timestamps and step metadata.

---

## 6. Agentic State Graphs & Coordination

### `StateGraph` & `CompiledStateGraph`
Cyclic execution graphs for autonomous agent loops with reflection:
- `StateGraph()`: Register nodes via `.add_node(name, callable)` and edges via `.add_edge(from_node, to_node)` or `.add_conditional_edges(from_node, router_fn)`.
- `START`, `END`: Sentinel nodes defining entry and terminal states.
- `.compile(checkpointer: StateCheckpointer | None = None) -> CompiledStateGraph`
- `CompiledStateGraph.invoke(initial_state: dict, max_iterations: int = 50) -> StateGraphResult`

### Dynamic Task Mapping & Branching
- `map_tasks(collection: list[Any], task_template_fn: Callable[[Any], Task]) -> list[Task]`: Dynamic fan-out.
- `fan_in_task(task_id: str, dependencies: list[str], aggregator_fn: Callable) -> Task`: Fan-in aggregation.
- `evaluate_branch(rule_fn, context) -> BranchDecision`: Evaluates dynamic condition.
- `apply_branch_decision(workflow, decision) -> None`: Activates selected branches, cancelling unchosen paths.

### Human-in-the-Loop Signals
- `SignalBroker(conn: sqlite3.Connection)`: Coordinate approvals and external events.
- `SignalTimeoutError`: Raised when awaiting an external signal expires.
- `default_signal_broker`: Module-level default broker.

---

## 7. Streaming & Process Sandboxing

### Zero-Memory Streaming
- `StreamPipe(conn: sqlite3.Connection, max_ram_buffer: int = 100)`: O(1) memory generator stream pipe with automatic SQLite disk spooling on consumer backpressure.
- `run_streaming_pipeline(producer_gen, consumer_fn, pipe: StreamPipe) -> dict`: Executes streaming pipeline.

### Priority Task Queue
- `PriorityTaskQueue(conn: sqlite3.Connection, max_concurrency_per_tenant: int = 5)`: Multi-priority scheduling (`TaskPriority.CRITICAL`, `HIGH`, `DEFAULT`, `BATCH`) with fair multi-tenant quotas.

### POSIX Subprocess Sandboxing
- `ResourceLimits(max_memory_mb: int | None, max_cpu_seconds: int | None, max_open_files: int | None)`
- `sandboxed_run(func, *args, limits: ResourceLimits = ..., timeout_seconds: float = ..., **kwargs)`
- `@sandboxed(max_memory_mb=128, timeout_seconds=10.0)`: Subprocess decorator enforcing kernel-level resource quotas.

### Distributed Worker Cluster
- `CoordinatorServer(host="0.0.0.0", port=9100, conn=conn)`: Standalone HTTP coordinator coordinating remote task leases and heartbeats.
- `WorkerAgent(coordinator_url="http://127.0.0.1:9100", worker_id=...)`: Standalone worker daemon polling and executing tasks over HTTP.

---

## 8. Enterprise Lifecycle & Data Governance

### Durable Timers & Suspensions
- `TimerStore(conn: sqlite3.Connection)`: SQLite-backed timer persistence.
- `DurableTimer`: Dataclass holding timer id, wake_at, and payload.
- `TimerStatus`: `PENDING`, `FIRED`, `CANCELLED`.
- `create_sleep_marker(seconds: float) -> dict`: Signals durable sleep pause without holding OS threads.
- `DURABLE_SLEEP_KEY`: Magic metadata key identifying durable timer suspensions.

### Runtime Data Contracts
- `DataContract(fields=[Field("name", type=str, min_length=1)])`: Schema validator.
- `Field(name: str, type: type, required: bool = True, min_value=..., max_value=..., regex=...)`
- `ContractValidationError`: Raised when data violates contract bounds.
- `@enforce_contract(inputs=..., outputs=...)`: Decorator validating task inputs/outputs.

### Chaos Engineering
- `ChaosPolicy(failure_rate: float = 0.0, latency_seconds: float = 0.0, jitter_seconds: float = 0.0, exception_factory=...)`
- `ChaosInjector(policy: ChaosPolicy)`: Injects synthetic failures into workflows.
- `ChaosFaultError`: Exception injected by chaos policies.
- `@with_chaos(policy)`: Decorator applying chaos fault injection.

### Time-Travel Replay & Run Forking
- `WorkflowReplaySnapshot`: Point-in-time DAG state reconstruction.
- `time_travel_inspect(conn, run_id: str, at_step: int | None = None, at_timestamp: float | None = None) -> WorkflowReplaySnapshot`
- `fork_run_from_task(conn, source_run_id: str, restart_from_task_id: str) -> str`: Forks execution from a checkpoint without repeating succeeded steps.

### Semantic Workflow Versioning & Code Drift
- `WorkflowVersionRegistry()`: Tracks registered workflow hashes.
- `compute_workflow_hash(workflow: Workflow) -> str`: Generates deterministic 16-character SHA-256 fingerprint.
- `compare_workflows(w1: Workflow, w2: Workflow) -> VersionDiff`: Details added/removed/modified tasks.
- `MigrationPolicy`: `FAIL_FAST`, `DRAIN`, `AUTO_MIGRATE`.

### Distributed Idempotency
- `IdempotencyStore(conn: sqlite3.Connection)`: 3-phase state locking (`PENDING`, `COMMITTED`, `ABORTED`) with TTL expiration.
- `IdempotencyRecord`, `IdempotencyStatus`, `IdempotencyConflictError`
- `@idempotent(store, key_builder)`: Decorator ensuring exactly-once execution.

### Reactive Event Bus & Webhook Server
- `EventBus()`: Wildcard topic pub/sub engine (`orders.*`).
- `Event`, `EventSubscription`
- `WebhookServer(bus: EventBus, host="127.0.0.1", port=8080)`: Zero-dependency stdlib HTTP webhook listener.

### Run-Scoped Shared Blackboard
- `WorkflowBlackboard(conn: sqlite3.Connection, run_id: str)`: Atomic shared memory.
- `.set(key, value)`, `.get(key, default=None)`
- `.increment(key, delta=1) -> int`: Atomic counter increment.
- `.compare_and_swap(key, expected_value, new_value) -> bool`: Optimistic locking CAS.

### Automated SLA Monitoring
- `SLAMonitor()`: Business deadline tracker.
- `SLAPolicy(deadline_seconds: float, warning_ratio: float = 0.75, on_warning=..., on_breach=...)`
- `SLABreachRecord`: Dataclass capturing breach details.

### Storage Retention & Compaction
- `compact_event_log(conn, completed_before_iso: str | None = None) -> int`: Prunes intermediate step events down to atomic terminal snapshots.
- `export_cold_archive(conn, destination_dir: str, older_than_days: int = 30) -> str`: Bundles completed runs into `.tar.gz` cold archives.
- `vacuum_database(conn) -> None`: Performs non-blocking SQLite database vacuum to reclaim disk space.

### Incremental Watermarking & Execution Plan
- `WatermarkStore(conn)`: Stateful checkpoint store tracking offsets across ETL runs.
- `Watermark(pipeline_id, high_watermark, updated_at)`
- `generate_execution_plan(workflow) -> ExecutionPlan`: Static topology analysis.
- `ExecutionPlan`, `ExecutionStage`: Topological stage partitioning and critical path estimation.

### Hierarchical Sub-Workflows
- `SubWorkflowResult`: Dataclass containing `run_id`, `status`, and `outputs`.
- `execute_subworkflow(parent_run_id, task_id, subworkflow, child_task_runner, conn_factory, scoped_inputs=...) -> SubWorkflowResult`: Runs child workflow and captures output map.
- `make_subworkflow_runner(subworkflow, child_task_runner, conn_factory, input_mapper=...) -> Callable[[Task], TaskResult]`: Creates task runner embedding child workflow.
- `get_subworkflow_tree(conn, root_run_id: str) -> dict`: Returns hierarchical parent-to-child run tree dictionary.

### Incremental DAG Evaluation & Content-Addressable Cache
- `compute_task_hash(task_id, code_fingerprint, explicit_inputs, upstream_outputs) -> str`: Deterministic SHA-256 fingerprint.
- `IncrementalStore(conn_or_path: sqlite3.Connection | str)`: Persistent content-addressed memoization cache.
- `IncrementalRunResult`: Dataclass tracking execution statistics (`total_tasks`, `executed_count`, `skipped_count`, `skipped_task_ids`).
- `wrap_incremental(store, runner, code_fingerprints=..., explicit_inputs=...) -> tuple[Callable[[Task], TaskResult], Callable[[], IncrementalRunResult]]`: Wraps task runner with caching.

### Adaptive Concurrency & Backpressure
- `AdaptiveConcurrencyPolicy(min_concurrency=1, max_concurrency=32, initial_concurrency=4, latency_threshold_seconds=2.0, backoff_factor=0.5, increase_step=1, max_cpu_load=0.0)`
- `AdaptiveConcurrencyController(policy: AdaptiveConcurrencyPolicy)`: Real-time AIMD latency/failure worker pool auto-tuner.
  - `.current_concurrency`: Dynamic current worker limit.
  - `.record_success(duration_seconds: float) -> None`
  - `.record_failure(duration_seconds: float | None = None) -> None`
  - `.create_hooks() -> Hooks`: Hooks dynamically feeding task lifecycle measurements.

### Compressed Blob Storage
- `BLOB_MARKER_KEY`: Constant key identifying offloaded blob payload metadata.
- `BlobReference(sha256, size_bytes, compressed_bytes, path)`: Dataclass pointer to stored blob.
- `BlobStore(storage_dir: str, compression_level: int = 6)`: Content-addressed zlib disk offload store.
  - `.put(data: bytes | str | Any) -> BlobReference`: Stores payload compressed.
  - `.get(ref: BlobReference | str) -> bytes`: Decompresses and retrieves payload.
  - `.offload_if_large(payload: Any, threshold_bytes: int = 65536) -> Any`: Transparently offloads payloads exceeding threshold.
  - `.resolve_if_blob(payload: Any) -> Any`: Transparently reloads blob reference if present.

### Multi-Node Replication & CDC Streaming
- `CDCRun`, `CDCEvent`, `CDCOutput`, `CDCBatch`: Dataclasses modeling CDC stream batches.
- `CDCReplicationSource(db_path: str)`: Change Data Capture extractor querying incremental state changes.
  - `.get_changes_since(after_event_id: int = 0, limit: int = 100) -> CDCBatch`
- `CDCReplicationTarget(db_path_or_conn: str | sqlite3.Connection)`: Ingests CDC batches into replica database.
  - `.apply_batch(batch: CDCBatch) -> int`
- `ReplicationServer(db_path: str, host: str = "0.0.0.0", port: int = 9200)`: Zero-dependency stdlib HTTP CDC publisher.
- `ReplicationClient(replica_conn_or_path: str | sqlite3.Connection, primary_url: str)`: Polling HTTP replication client.

### Distributed Work Stealing & Dead Worker Reclamation
- `WorkerNodeInfo`: Dataclass tracking worker id, capacity, active tasks, heartbeat, status, and host/port.
- `WorkStealingRegistry(conn_or_path: sqlite3.Connection | str)`: Multi-worker registry for dynamic load balancing.
  - `.register_worker(worker_id, capacity=4, host="127.0.0.1", port=0)`
  - `.heartbeat(worker_id, active_tasks=None)`
  - `.enqueue_task(task_id, assigned_worker_id=None, state="READY")`
  - `.steal_work(thief_worker_id, max_tasks=1) -> list[str]`: Steals ready tasks from overloaded peers.
  - `.reclaim_dead_workers(timeout_seconds=30.0) -> list[str]`: Marks unresponsive workers DEAD and returns tasks to READY pool.

### Historical Backfill & Deterministic Catchup Engine
- `CatchupPolicy`: `ALL`, `LATEST_ONLY`, `SLIDING_WINDOW`.
- `BackfillWindow(window_id, start_time, end_time, jitter_seconds, status, run_id)`
- `BackfillPlan(workflow_id, windows, catchup_policy)`
- `generate_backfill_plan(workflow_id, start_time, end_time, interval_seconds, catchup_policy=..., jitter_max_seconds=...) -> BackfillPlan`
- `BackfillExecutor(conn_or_path)`: Sequential and logged execution of temporal backfill windows.
  - `.run_plan(plan, workflow, task_runner, conn_factory=...) -> list[BackfillWindow]`

### Multi-Tenant Fair-Share & Hierarchical Quotas
- `TenantQuota(tenant_id, max_concurrent=10, rate_limit_per_second=100.0, burst_capacity=10.0)`
- `TenantUsage(tenant_id, active_concurrent, available_tokens, last_token_refill)`
- `TenantQuotaManager(default_quota=...)`: Thread-safe multi-tenant quota controller.
  - `.set_quota(quota)`
  - `.acquire(tenant_id, tokens=1.0) -> bool`
  - `.release(tenant_id) -> None`
  - `.wrap_tenant_task(tenant_id, runner, raise_on_quota=False) -> Callable[[Task], TaskResult]`
  - `.create_hooks(tenant_resolver) -> Hooks`

### Task Mutation Interceptors & Middleware Pipeline
- `TaskExecutionContext(task, run_id, metadata, start_time, end_time, attempt)`
- `Middleware`: `Callable[[TaskExecutionContext, Callable[[TaskExecutionContext], TaskResult]], TaskResult]`
- `MiddlewarePipeline()`: Composable onion-style execution pipeline.
  - `.use(middleware) -> MiddlewarePipeline`
  - `.execute(context, handler) -> TaskResult`
  - `.wrap_runner(runner, run_id="") -> Callable[[Task], TaskResult]`
- Built-in Middlewares:
  - `secret_masking_middleware(secret_keys=..., mask_value="***REDACTED***")`
  - `execution_timer_middleware(metric_collector=...)`
  - `audit_logging_middleware(log_sink=...)`

### Self-Healing Workflow Watchdog & Auto-Supervisor
- `AutoRemedy`: `RETRY`, `ABORT_RUN`, `NOTIFY`.
- `ZombieTaskIncident(incident_id, run_id, task_id, elapsed_seconds, remedy_applied, reason, created_at)`
- `SupervisorPolicy(stuck_timeout_seconds=300.0, default_remedy=AutoRemedy.RETRY, max_auto_retries=3)`
- `WorkflowSupervisor(conn_or_path, policy=...)`: Watchdog scanning active SQLite runs for stalled or abandoned tasks.
  - `.scan_and_heal() -> list[ZombieTaskIncident]`
  - `.get_incidents(run_id=None) -> list[ZombieTaskIncident]`

---

## 9. Exceptions

All engine exceptions inherit from `OrchestrationError`:

```
OrchestrationError (built-in Exception)
├── WorkflowValidationError (subclasses ValueError)
├── WorkflowDefinitionError (subclasses ValueError)
├── PersistenceError (wraps sqlite3.Error)
├── SignalTimeoutError
├── CircuitBreakerOpenError
├── ContractValidationError
├── ChaosFaultError
├── IdempotencyConflictError
└── TenantQuotaExceededError
```
