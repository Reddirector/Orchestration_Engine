# Orchestration-Engine

[![PyPI version](https://img.shields.io/pypi/v/orchestration-engine.svg)](https://pypi.org/project/orchestration-engine/)
[![Python versions](https://img.shields.io/pypi/pyversions/orchestration-engine.svg)](https://pypi.org/project/orchestration-engine/)
[![License](https://img.shields.io/badge/license-MIT%20%7C%20Apache--2.0-blue.svg)](https://github.com/Reddirector/Orchestration_Engine/blob/main/LICENSE)
[![CI Status](https://github.com/Reddirector/Orchestration_Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Reddirector/Orchestration_Engine/actions)

A fault-tolerant workflow orchestration engine. Define tasks with dependencies, retry policies, and timeouts as JSON; the engine handles scheduling, execution ordering, retries with exponential backoff, timeouts, and state persistence — you supply the logic for each task.

## Features

- **Dependency-aware scheduling**: Tasks execute as soon as their upstream dependencies succeed.
- **Configurable retries & exponential backoff**: Base delay doubles on each attempt (`delay_seconds * 2**(attempt_count - 1)`).
- **Fault-tolerant exception handling**: Exceptions in task runners share the retry policy; `task.last_error` records error details.
- **Enforced timeouts**: Per-task timeouts (default 30.0s) enforced asynchronously without blocking the engine coordinator.
- **Transitive cancellation**: When a task fails permanently, all downstream dependents are cancelled to a fixpoint.
- **SQLite-backed audit trail**: Append-only event log with write-ahead persistence of state transitions.
- **Zero runtime dependencies**: Pure Python standard library implementation.

## Installation

Install from PyPI:

```bash
pip install orchestration-engine
```

For optional YAML workflow loading support (`load_workflow_from_yaml`):

```bash
pip install "orchestration-engine[yaml]"
```

> **Note for Linux users (PEP 668):** If your Linux distribution (Ubuntu 23.04+, Debian 12+) manages Python packages externally, activate a virtual environment first:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install orchestration-engine
> ```
> Or install using `uv pip install orchestration-engine` or `pipx install orchestration-engine`.

## Quickstart

Define a workflow as JSON — two tasks, the second depending on the first:

```json
{
  "workflow_id": "wf-1",
  "name": "example-workflow",
  "description": "A minimal two-task workflow",
  "default_timeout_seconds": 30.0,
  "tasks": [
    {
      "task_id": "fetch-data",
      "name": "Fetch data",
      "description": "Pulls input data",
      "dependencies": [],
      "retry_policy": { "max_attempts": 3, "delay_seconds": 1.0 },
      "timeout_seconds": 15.0
    },
    {
      "task_id": "process-data",
      "name": "Process data",
      "description": "Processes the fetched data",
      "dependencies": ["fetch-data"],
      "retry_policy": { "max_attempts": 3, "delay_seconds": 2.0 },
      "timeout_seconds": 30.0
    }
  ]
}
```

Run it:

```python
import time
from orchestration_engine import get_connection, run_workflow_from_file

def task_runner(task) -> bool:
    print(f"Running task: {task.name}")
    # Return True on success, False on failure (triggers retry per the task's retry_policy).
    # Unhandled exceptions are also caught and retried per policy.
    return True

conn = get_connection("my_workflows.db")  # or ":memory:"
status = run_workflow_from_file("workflow.json", task_runner, time.time, conn)
print(status)  # WorkflowStatus.SUCCEEDED
```

## Command-Line Interface (CLI)

`orchestration-engine` includes a full-featured CLI for executing workflows, dry-run simulation, triage, and observability:

```bash
# Dry-run analysis: topological execution stages, critical path, parallelism
orchestration-engine plan workflow.json [--json]

# Validate workflow schema and acyclic structure
orchestration-engine validate examples/simple_workflow.json

# Run workflow with SQLite state persistence and retry coordination
orchestration-engine run examples/simple_workflow.json --runner examples.runners:run --db workflows.db

# Inspect run status, transition history, and run list
orchestration-engine status <run_id> --db workflows.db
orchestration-engine history <run_id> --db workflows.db
orchestration-engine runs --db workflows.db

# Inspect and manage Dead Letter Queue (DLQ)
orchestration-engine dlq list --db workflows.db [--json]
orchestration-engine dlq purge --db workflows.db [--older-than 86400]

# Export microsecond Chrome Trace / Perfetto format
orchestration-engine trace <run_id> --db workflows.db -o trace.json

# Send external human approval or webhook signal
orchestration-engine signal <run_id> approval --payload '{"approved": true}' --db workflows.db
```

For full CLI documentation, exit codes, and JSON schemas, see [docs/cli.md](docs/cli.md).

## Modern Features & Enterprise Capabilities

### 1. Ergonomic Decorators (`@task` & `@workflow`)
Author clean, type-safe DAGs natively in Python without writing JSON:

```python
import asyncio
from orchestration_engine import task, workflow

@task(timeout_seconds=5.0)
def fetch_data() -> dict:
    return {"users": ["alice", "bob"]}

@task(dependencies=["fetch_data"])
def process(data: dict) -> int:
    return len(data["users"])

@workflow(name="modern-pipeline")
def modern_pipeline():
    return [fetch_data, process]

# Run synchronously or asynchronously:
result = modern_pipeline.run()
# or: result = asyncio.run(modern_pipeline.run_async())
```

### 2. High-Throughput Async Coordinator (`run_workflow_async`)
Coordinate 1,000+ concurrent I/O-bound tasks natively with non-blocking timeouts and zero OS thread overhead:

```python
import asyncio
from orchestration_engine import run_workflow_async

async def async_runner(task):
    await asyncio.sleep(0.01)
    return {"status": "ok"}

status = asyncio.run(run_workflow_async(workflow, async_runner, max_concurrency=100))
```

### 3. Dynamic Task Mapping & Fan-Out / Fan-In
Dynamically expand tasks across collections at runtime and aggregate results with a downstream reducer:

```python
from orchestration_engine import WorkflowBuilder

workflow = (
    WorkflowBuilder("fanout-pipeline")
    .task("split", name="Partition Records")
    .map_tasks(
        base_task_id="transform_part",
        items=["batch_1", "batch_2", "batch_3", "batch_4"],
        dependencies=["split"],
        reducer_task_id="reduce_all",
        reducer_name="Aggregate All Partitions",
    )
    .build()
)
```

### 4. Cron & Recurring Scheduler Daemon
Run workflows on fixed intervals or standard 5-field cron schedules with zero external dependencies:

```python
from orchestration_engine import WorkflowScheduler, CronSchedule, IntervalSchedule

scheduler = WorkflowScheduler()

# Run every 15 minutes during business hours:
scheduler.add_job(
    job_id="cron-etl",
    workflow_factory=lambda: workflow,
    schedule=CronSchedule("*/15 9-17 * * 1-5"),
    task_runner=task_runner,
)

# Start background scheduler loop:
scheduler.start(daemon=True)
```

### 5. Human-in-the-Loop & External Signals
Pause workflow tasks awaiting external approval, manager signoff, or webhook payloads:

```python
from orchestration_engine import default_signal_broker

def approval_step(task):
    # Synchronously or asynchronously await human signoff:
    signal = default_signal_broker.wait_for_signal(task._run_id, "deployment_approval", timeout=300.0)
    if not signal.get("approved"):
        raise RuntimeError("Deployment rejected")
    return {"status": "deployed"}

# External actors can deliver signals via Python, CLI, or the Web Dashboard:
default_signal_broker.send_signal(run_id, "deployment_approval", payload={"approved": True})
```

### 6. Token-Bucket Rate Limiter & SQLite Result Caching
Defend against LLM API rate limits (`HTTP 429`) and memoize deterministic step outputs:

```python
from orchestration_engine import TokenBucketRateLimiter, TaskCache

limiter = TokenBucketRateLimiter(rate=10.0, capacity=10)
cache = TaskCache("cache.db", default_ttl=3600.0)

@task
async def call_llm(prompt: str) -> dict:
    async with limiter:
        cached = cache.get("call_llm", prompt=prompt)
        if cached:
            return cached
        res = {"text": f"Output for {prompt}"}
        cache.set("call_llm", res, prompt=prompt)
        return res
```

## Durability and Crash Recovery

Every execution is tracked as a distinct run with an explicit or automatically generated `run_id`:

```python
import time
from orchestration_engine import get_connection, run_workflow, resume_run, get_run_status, list_runs

conn = get_connection("workflows.db")

# Run a workflow and obtain its run_id
run_id = run_workflow(workflow, {}, time.time, task_runner, conn)

# Query run status directly from SQLite
status = get_run_status(conn, run_id)

# List all recorded runs
runs = list_runs(conn, workflow_id="wf-1")

# If a process was interrupted or crashed (e.g. host reboot, SIGKILL), resume it:
resumed_status = resume_run(conn, run_id, task_runner, time.time)
# Completed tasks are never re-run; interrupted tasks are retried per policy.
```

## Concurrency

Tasks can be executed concurrently up to `max_concurrency` using either threads or spawned child processes:

```python
# Run with up to 4 parallel workers using threads
run_id = run_workflow(
    workflow,
    task_states,
    time.time,
    task_runner,
    conn,
    max_concurrency=4,
    executor="thread",
)

# Run with isolated child processes
run_id = run_workflow(
    workflow,
    task_states,
    time.time,
    task_runner,
    conn,
    max_concurrency=4,
    executor="process",
)
```

### Architecture: Single-Writer Coordinator
- **Safety**: The main coordinator thread calling `run_workflow` retains exclusive access to SQLite and performs all state transitions. No database connections are ever shared across threads or processes, completely eliminating `sqlite3.ProgrammingError` or database contention.
- **Thread Backend (`executor="thread"`)**: Lightweight concurrency using `concurrent.futures.ThreadPoolExecutor`. Note that Python threads cannot be preemptively killed; a timed-out task is abandoned by the coordinator and marked failed/retried, while its thread runs to completion in the background.
- **Process Backend (`executor="process"`)**: True process isolation using `multiprocessing.get_context("spawn")`. On timeout, child processes are terminated with `SIGTERM` and killed with `SIGKILL` after a short grace period. Requires `task_runner` to be picklable.

## Data Flow and Outputs

Tasks can return a `TaskResult(ok=True, output=...)` to pass data to downstream dependents:

```python
from orchestration_engine import TaskResult

def task_runner(task):
    if task.task_id == "fetch_user":
        return TaskResult(ok=True, output={"user_id": 42, "name": "Alice"})
    elif task.task_id == "greet":
        # Upstream outputs are automatically injected into task.inputs
        user = task.inputs["fetch_user"]
        return TaskResult(ok=True, output=f"Hello, {user['name']}!")
    return TaskResult(ok=True)
```

Outputs are persisted in SQLite under Schema v2 and automatically restored upon workflow resumption.

## Lifecycle Hooks

Observe workflow and task state changes safely:

```python
from orchestration_engine import Hooks

hooks = Hooks(
    on_task_start=lambda task: print(f"Started: {task.name}"),
    on_task_succeeded=lambda task: print(f"Succeeded: {task.name}"),
    on_task_retry=lambda task: print(f"Retrying: {task.name}"),
    on_task_failed=lambda task: print(f"Failed: {task.name}"),
    on_workflow_done=lambda wf, status: print(f"Finished: {status.value}"),
)

run_workflow(workflow, {}, time.time, task_runner, conn, hooks=hooks)
```

Hooks execute *after* state transitions are persisted to SQLite. Any exception raised inside a hook is caught and suppressed to prevent user hook bugs from interrupting workflow execution.

## Fluent Workflow Builder

Construct and validate workflows with a fluent chaining API:

```python
from orchestration_engine import WorkflowBuilder, workflow_to_dict

workflow = (
    WorkflowBuilder("etl-wf", "ETL Pipeline")
    .description("Extract, transform, and load data")
    .default_timeout(60.0)
    .task("extract", name="Extract Records")
    .task("transform", name="Transform Records", dependencies=["extract"], max_attempts=3)
    .task("load", name="Load to DB", dependencies=["transform"])
    .build()
)

# Losslessly serialize to JSON dictionary:
wf_dict = workflow_to_dict(workflow)
```

## Real-World Use Cases

The repository includes runnable simulated pipeline examples (using clean stubs with zero external SDK dependencies) in `examples/`:

- **[Enterprise Resilience & Fintech Sagas](examples/enterprise_resilience.py)**: Distributed Sagas with compensating rollbacks, persistent Circuit Breakers, Dead Letter Queue (DLQ) triage, distributed advisory leasing without Redis, and incremental watermark checkpointing.
- **[Multi-Step AI Agent Pipeline](examples/agent_pipeline.py)**: Orchestrates LLM tool calling, document retrieval, automated retries on transient API rate limits (`HTTP 429`), concurrent entity extraction, and fan-in executive summary synthesis.
- **[RAG Knowledge Ingestion & Vector Indexing](examples/rag_document_indexer.py)**: Semantic document chunking, parallel embedding generation with transient backpressure handling, vector store upsert, and an automated quality evaluation gate.
- **[Autonomous Incident Triage & Remediation](examples/incident_triage.py)**: SRE incident response workflow running parallel diagnostics across logs, metrics, and service dependencies (`max_concurrency=3`), synthesizing root cause analysis (RCA), executing automated remediation, and verifying health recovery.
- **[Resilient Data Flow & ETL](examples/data_flow.py)**: Producer-consumer data flow where task outputs pass cleanly downstream via `task.inputs` with full transactional persistence.

See the complete [Use Cases Documentation](docs/use-cases.md) for architectural diagrams and deep dives.

## Enterprise Resilience & Production Tooling

### 1. Distributed Sagas with Compensating Rollbacks
In microservices, fintech, and multi-step distributed operations, transactions cannot span across external systems in a single ACID database transaction. If any step fails, `run_saga` automatically executes compensating actions (undo operations) in **reverse topological order** of the steps that previously succeeded:

```python
from orchestration_engine import WorkflowBuilder, run_saga

wf = (
    WorkflowBuilder("order-saga")
    .task("reserve_inventory")
    .task("charge_card", dependencies=["reserve_inventory"])
    .task("provision_license", dependencies=["charge_card"])
    .build()
)

# If provision_license fails, charge_card is refunded, then inventory is released
result = run_saga(
    wf,
    task_runner=runners,
    compensators={
        "charge_card": lambda task_output, run_id: refund_payment(task_output["charge_id"]),
        "reserve_inventory": lambda task_output, run_id: release_stock(task_output["sku"]),
    },
    db_path="orders.db",
)
print(result.status)  # SagaStatus.COMPENSATED
```

### 2. Resilient Circuit Breakers
Protect downstream services (e.g. OpenAI, Stripe, internal databases) from cascading outages. When consecutive failures exceed a threshold, the circuit trips to `OPEN`, immediately fast-failing calls without tying up worker threads or network sockets:

```python
from orchestration_engine import CircuitBreaker, CircuitBreakerOpenError

cb = CircuitBreaker("llm-gateway", failure_threshold=3, recovery_timeout=15.0)

@cb.protect
def generate_summary(text: str) -> str:
    return call_external_api(text)

try:
    summary = generate_summary("...")
except CircuitBreakerOpenError as exc:
    # Fast-fail immediately without wasting network I/O
    print(f"Service offline, recovery trial in {exc.recovery_time_remaining:.1f}s")
```

### 3. Persistent Dead Letter Queue (DLQ)
When a task exhausts all retry attempts or encounters fatal errors, it is dispatched to a persistent SQLite-backed Dead Letter Queue preserving inputs, error messages, attempt counts, and stack traces for post-mortem triage:

```python
from orchestration_engine import DeadLetterQueue, create_dlq_hook

dlq = DeadLetterQueue("workflows.db")
hooks = create_dlq_hook(dlq, workflow_id="etl-sync", run_id="run-102")

# List failed tasks needing human investigation
failed_messages = dlq.list_messages(workflow_id="etl-sync")
for msg in failed_messages:
    print(f"Task {msg.task_id} failed with {msg.error_message}")

# Replay and auto-purge upon successful fix
dlq.replay(failed_messages[0].message_id, runner_func=fixed_runner)
```

### 4. Distributed Advisory Leases (No Redis Required)
Coordinate multi-worker cron jobs and partitioned tasks across multiple machines or container instances using SQLite WAL atomic leases:

```python
from orchestration_engine import TaskLease

# Automatic heartbeat renewal in the background while inside context
with TaskLease("shared.db", "partition-europe", "worker-node-1", ttl_seconds=30.0):
    # Only one worker can hold this lease at any given moment
    sync_partition_data()
```

### 5. Stateful Incremental ETL Watermarks
Track high-watermarks (e.g. `last_processed_timestamp`, `kafka_offset`, `row_id`) atomically within the database:

```python
from orchestration_engine import WatermarkStore

store = WatermarkStore("etl.db")
last_synced = store.get_watermark("users-cdc", "updated_at", default=0.0)
# Process batch...
store.advance_watermark("users-cdc", "updated_at", current_max_timestamp)
```

### 6. Dry-Run Execution Plan
Inspect topological execution stages, critical path, and maximum worker parallelism prior to execution:

```python
from orchestration_engine import WorkflowBuilder, generate_execution_plan

wf = WorkflowBuilder("pipeline").task("a").task("b", dependencies=["a"]).build()
plan = generate_execution_plan(wf)
print(f"Critical Path: {' -> '.join(plan.critical_path)}")
print(f"Max Parallelism: {plan.max_parallelism}")
```

### 7. Agentic State Graphs & Cyclic Loops
Unlike DAGs which strictly forbid cycles, autonomous multi-agent AI systems require reflection, test-and-evaluate feedback, and self-correction loops. `StateGraph` enables cyclic graph execution with safety iteration limits (`max_iterations`) and persistent SQLite thread checkpointing:

```python
from orchestration_engine import StateGraph, StateCheckpointer, START, END

builder = StateGraph()
builder.add_node("draft", draft_agent)
builder.add_node("critique", critique_agent)
builder.add_node("refine", refine_agent)

builder.add_edge(START, "draft")
builder.add_edge("draft", "critique")
builder.add_conditional_edges(
    "critique",
    lambda state: END if state.get("approved") else "refine"
)
builder.add_edge("refine", "critique")

app = builder.compile(checkpointer=StateCheckpointer("agent.db"), max_iterations=10)
result = app.invoke({"task": "Draft RFC"}, thread_id="thread-101")
print(result.final_state)
```

### 8. Zero-Memory Streaming Tasks with Disk Spooling
Stream high-volume records, LLM token generators, or large datasets item-by-item in $O(1)$ constant RAM. When the consumer is slower than the producer, `StreamPipe` automatically spills excess items to an SQLite ring-buffer table, mitigating backpressure:

```python
from orchestration_engine import StreamPipe, run_streaming_pipeline

def producer(pipe: StreamPipe):
    for record in generate_millions_of_records():
        pipe.push(record)

def consumer(pipe: StreamPipe):
    total = sum(r["val"] for r in pipe)
    return total

result = run_streaming_pipeline(producer, consumer, max_buffer_size=100, spill_db_path="spool.db")
```

### 9. Priority Scheduling & Fair Multi-Tenant Queuing
Schedule tasks by urgency (`CRITICAL`, `HIGH`, `DEFAULT`, `BATCH`) while enforcing per-tenant concurrency limits to prevent noisy-neighbor starvation:

```python
from orchestration_engine import PriorityTaskQueue, TaskPriority

queue = PriorityTaskQueue(tenant_concurrency_limit=2)
queue.push(task_1, priority=TaskPriority.BATCH, tenant_id="tenant-free")
queue.push(task_2, priority=TaskPriority.CRITICAL, tenant_id="tenant-enterprise")

# High priority and fair tenant slots are dequeued first
next_task = queue.pop()
```

### 10. POSIX Resource Sandboxing
Isolate untrusted code or memory-intensive tasks in an isolated subprocess with kernel-enforced RAM and CPU limits:

```python
from orchestration_engine import sandboxed, ResourceLimits

@sandboxed(max_memory_mb=256, timeout_seconds=10.0)
def untrusted_user_script(code_str: str):
    # If this exceeds 256MB RAM or 10s CPU, it is safely killed with MemoryError/TimeoutError
    exec(code_str)
```

### 11. Zero-Dependency Distributed Worker Cluster
Scale task execution across multiple servers or container nodes with zero external brokers (no Celery, Redis, or RabbitMQ). The built-in stdlib HTTP `CoordinatorServer` and `WorkerAgent` orchestrate task dispatch, polling, heartbeats, and result collection over clean REST endpoints:

```bash
# On coordinator node:
orchestration-engine coordinator --host 0.0.0.0 --port 9100 --db cluster.db

# On worker nodes:
orchestration-engine worker --coordinator http://coordinator-ip:9100
```

### 12. Durable Timers & Workflow Suspensions
Suspend workflows and schedule long-running wakeups (hours, days, or weeks) in SQLite without holding worker threads or processes open in memory:

```python
from orchestration_engine import TimerStore

store = TimerStore("workflows.db")
timer = store.create_timer(run_id="run-1", task_id="signoff", delay_seconds=86400.0)

# Check and fire due timers on scheduler tick:
for due in store.get_due_timers():
    store.mark_timer_fired(due.timer_id)
```

### 13. Runtime Data Contracts & Output Validation
Ensure type safety and prevent missing-key runtime exceptions between connected tasks with zero external dependencies:

```python
from orchestration_engine import DataContract, Field, enforce_contract

user_contract = DataContract({
    "user_id": Field(type=str, regex=r"^usr_"),
    "tier": Field(choices={"free", "pro"}),
    "score": Field(type=float, min_val=0.0, max_val=100.0),
})

@enforce_contract(output_contract=user_contract)
def fetch_user_data() -> dict:
    return {"user_id": "usr_42", "tier": "pro", "score": 98.5}
```

### 14. Chaos Engineering & Fault Injection
Test distributed sagas, retries, and circuit breakers against simulated transient failures and network jitter before going to production:

```python
from orchestration_engine import ChaosPolicy, with_chaos

policy = ChaosPolicy(
    failure_rate=0.25,  # 25% failure injection
    latency_seconds=0.1,
    latency_jitter_seconds=0.05,
    task_targets={"stripe_charge"},
)

@with_chaos(policy)
def stripe_charge(payload: dict) -> dict:
    return call_payment_api(payload)
```

### 15. Time-Travel Inspection & Forked Replay
Inspect the exact task state and output snapshot at any historical event step $N$ or timestamp $T$, and fork runs from a failed step without re-executing costly upstream computations:

```python
from orchestration_engine import time_travel_inspect, fork_run_from_task, resume_run

# 1. Inspect state at historical step 4
snapshot = time_travel_inspect(conn, run_id="failed-run", at_step=4)
print(snapshot.task_states)

# 2. Fork execution from failed step 'generate_embeddings'
new_run_id = fork_run_from_task(conn, "failed-run", restart_from_task_id="generate_embeddings")
# Resumes using inherited outputs from step 1 without re-running earlier tasks:
status = resume_run(conn, new_run_id, fixed_runner)
```

### 16. Semantic Workflow Versioning & Drift Detection
Detect code topology drift between active definitions and persisted in-flight runs using deterministic 16-character SHA-256 fingerprints, with configurable migration policies (`FAIL_FAST`, `DRAIN`, `AUTO_MIGRATE`):

```python
from orchestration_engine import WorkflowVersionRegistry, compute_workflow_hash, MigrationPolicy

registry = WorkflowVersionRegistry()
v1_hash = registry.register(workflow_v1)

# Verify whether an in-flight run can safely continue under updated code:
can_proceed, reason = registry.check_migration(
    active_workflow=workflow_v2,
    run_definition_json=persisted_json,
    policy=MigrationPolicy.AUTO_MIGRATE,
)
```

### 17. Distributed Idempotency & Exactly-Once Keys
Guarantee exactly-once execution across retries and distributed triggers using atomic SQLite state locks (`PENDING`, `COMMITTED`, `ABORTED`) and TTL expiration:

```python
from orchestration_engine import IdempotencyStore, idempotent

store = IdempotencyStore(conn)

# Explicit acquire/commit workflow:
record = store.acquire("payment_order_4821", ttl_seconds=300)
if record is None:
    cached_output = store.get_result("payment_order_4821")
else:
    output = {"status": "paid", "tx": "tx_9981"}
    store.commit("payment_order_4821", output=output)

# Declarative function decorator:
@idempotent(store=store, key_builder=lambda order_id: f"charge_{order_id}")
def charge_customer(order_id: str) -> dict:
    return {"status": "paid", "amount": 99.0}
```

### 18. Event-Driven Webhooks & Reactive Topic Bus
Publish and subscribe to reactive runtime events using wildcards (`orders.*`), with a zero-dependency stdlib HTTP webhook listener:

```python
from orchestration_engine import EventBus, WebhookServer

bus = EventBus()
bus.subscribe("orders.*", lambda event: print(f"Received {event.topic}: {event.payload}"))

# Start non-blocking HTTP webhook server on port 8080:
server = WebhookServer(bus=bus, host="127.0.0.1", port=8080)
server.start()
# Inbound POST http://127.0.0.1:8080/webhook/orders.created dispatches to the bus
server.stop()
```

### 19. Run-Scoped Shared Blackboard & Atomic KV Memory
Coordinate state across distributed tasks in a DAG without polluting output dictionaries, featuring optimistic Compare-And-Swap (CAS) and atomic counters:

```python
from orchestration_engine import WorkflowBlackboard

blackboard = WorkflowBlackboard(conn, run_id="order-run-102")
blackboard.set("inventory_reserved", True)

# Atomic counter increments:
blackboard.increment("items_processed", delta=5)

# Optimistic lock / Compare-And-Swap:
swapped = blackboard.compare_and_swap(
    key="status",
    expected_value="pending",
    new_value="processing"
)
```

### 20. Automated SLA Deadlines & Escalation Alerts
Define business SLA policies per task or workflow with proactive warning thresholds and automatic escalation callbacks:

```python
from orchestration_engine import SLAMonitor, SLAPolicy

monitor = SLAMonitor()
monitor.register_sla(
    task_id="fraud_check",
    policy=SLAPolicy(
        deadline_seconds=2.0,
        warning_ratio=0.75,  # Trigger warning at 1.5s
        on_warning=lambda tid, elapsed, dl: print(f"Warning: {tid} near breach ({elapsed:.1f}s)"),
        on_breach=lambda tid, elapsed, dl: print(f"SLA BREACH: {tid} exceeded {dl}s!"),
    ),
)
monitor.start_task("fraud_check")
# ... execution ...
monitor.complete_task("fraud_check")
```

### 21. Tiered Cold-Archival & SQLite Log Compaction
Prevent unbounded database growth by compacting terminal run event logs down to atomic summary entries, exporting compressed `.tar.gz` cold archives, and non-blocking vacuuming:

```python
from orchestration_engine import compact_event_log, export_cold_archive, vacuum_database

# Compact older terminal run events into a single terminal snapshot:
deleted_count = compact_event_log(conn, completed_before_iso="2026-01-01T00:00:00Z")

# Bundle completed runs into cold archive .tar.gz bundle:
archive_path = export_cold_archive(conn, destination_dir="/backup/archives", older_than_days=30)

# Reclaim database space:
vacuum_database(conn)
```

### 22. Hierarchical Sub-Workflows & Nested DAGs
Embed complete child workflows as discrete steps inside a parent workflow with scoped inputs, error propagation, and hierarchical tree inspection:

```python
from orchestration_engine import make_subworkflow_runner, get_subworkflow_tree

# Convert a child workflow into a task runner callable:
child_runner = make_subworkflow_runner(
    subworkflow=child_wf,
    child_task_runner=child_step_runner,
    conn_factory=lambda: get_connection("workflows.db"),
)

# Inspect full hierarchy of parent and nested child runs:
tree = get_subworkflow_tree(conn, root_run_id=parent_run_id)
```

### 23. Incremental DAG Evaluation & Content-Addressable Cache
Like `make` or `bazel` for workflows: skip executing tasks whose code signatures, explicit inputs, and upstream dependency outputs have not changed:

```python
from orchestration_engine import IncrementalStore, wrap_incremental

store = IncrementalStore("workflows.db")
wrapped_runner, get_summary = wrap_incremental(
    store=store,
    runner=task_runner,
    code_fingerprints={"transform": "v2.1", "train_model": "v1.4"},
)

# Tasks with identical inputs and code hashes reuse outputs instantly:
summary = get_summary()
print("Skipped from cache:", summary.skipped_task_ids)
```

### 24. Adaptive Concurrency & Backpressure Auto-Tuning
Dynamically auto-tune worker concurrency using AIMD (Additive Increase, Multiplicative Decrease) based on real-time task latency, transient error spikes, and system CPU load:

```python
from orchestration_engine import AdaptiveConcurrencyController, AdaptiveConcurrencyPolicy

policy = AdaptiveConcurrencyPolicy(
    min_concurrency=1,
    max_concurrency=20,
    initial_concurrency=4,
    latency_threshold_seconds=1.5,
    max_cpu_load=8.0,
)
ctrl = AdaptiveConcurrencyController(policy)
hooks = ctrl.create_hooks()

# Pass hooks to run_workflow; worker concurrency adapts automatically:
run_id = run_workflow(wf, task_states, time.time, runner, conn, hooks=hooks)
```

### 25. Compressed Blob Offloading for Massive Payloads
Prevent SQLite WAL database bloat by automatically compressing (`zlib`) and storing large task outputs (> threshold) in content-addressed local disk storage, keeping SQLite records lightweight:

```python
from orchestration_engine import BlobStore

blob_store = BlobStore(storage_dir="./blobs", compression_level=6)

# Automatically offload if payload exceeds threshold:
output_pointer = blob_store.offload_if_large(large_dataset, threshold_bytes=65536)

# Transparently decompress and restore when needed:
original_data = blob_store.resolve_if_blob(output_pointer)
```

### 26. Multi-Node Replication & CDC Stream Synchronization
Stream incremental database mutations (`task_events`, `task_outputs`, and `runs`) from a primary node to distributed read replicas over standard library HTTP:

```python
from orchestration_engine import ReplicationServer, ReplicationClient

# On Primary Node:
server = ReplicationServer(db_path="primary.db", host="0.0.0.0", port=9200)
server.start()

# On Replica Node:
client = ReplicationClient(replica_conn_or_path="replica.db", primary_url="http://10.0.0.1:9200")
synced_events = client.sync_once()
print(f"Synchronized {synced_events} events from primary.")
```

### 27. Distributed Work Stealing & Dead Worker Reclamation
Dynamically balance worker load across distributed cluster nodes by allowing under-utilized workers to steal ready tasks from overloaded peers, while automatically reclaiming orphaned tasks from dead or non-responsive worker nodes:

```python
from orchestration_engine import WorkStealingRegistry

registry = WorkStealingRegistry("cluster.db")
registry.register_worker("worker_alpha", capacity=4)
registry.register_worker("worker_beta", capacity=4)

# Under-utilized worker_beta steals up to 2 tasks from overloaded worker_alpha:
stolen_tasks = registry.steal_work("worker_beta", max_tasks=2)

# Watchdog detects crashed nodes (no heartbeat for 30s) and returns orphaned tasks to ready pool:
reclaimed_tasks = registry.reclaim_dead_workers(timeout_seconds=30.0)
```

### 28. Historical Backfill & Deterministic Catchup Engine
Re-run workflows across historical time windows with deterministic interval stepping, anti-thundering-herd pseudo-random jitter, and configurable catch-up policies (`ALL`, `LATEST_ONLY`, `SLIDING_WINDOW`):

```python
from orchestration_engine import BackfillExecutor, CatchupPolicy, generate_backfill_plan

plan = generate_backfill_plan(
    workflow_id="daily_metrics",
    start_time=1700000000.0,
    end_time=1700000500.0,
    interval_seconds=100.0,
    catchup_policy=CatchupPolicy.ALL,
    jitter_max_seconds=5.0,
)

executor = BackfillExecutor("workflows.db")
executed_windows = executor.run_plan(plan, workflow, task_runner)
```

### 29. Multi-Tenant Fair-Share & Hierarchical Quota Engine
Enforce strict per-tenant concurrency ceilings and token-bucket request rate limits across multi-tenant environments, protecting shared workers from noisy-neighbor starvation:

```python
from orchestration_engine import TenantQuota, TenantQuotaManager

manager = TenantQuotaManager()
manager.set_quota(TenantQuota(
    tenant_id="tenant_fintech",
    max_concurrent=5,
    rate_limit_per_second=20.0,
    burst_capacity=5.0,
))

# Wrap task runner with automatic quota acquisition and release:
tenant_runner = manager.wrap_tenant_task("tenant_fintech", base_task_runner)
```

### 30. Task Mutation Interceptors & Middleware Pipeline
Compose an onion-style execution stack around tasks for cross-cutting concerns (such as deep secret credential masking, precise execution duration timing, and immutable audit logs) without polluting business logic:

```python
from orchestration_engine import (
    MiddlewarePipeline,
    audit_logging_middleware,
    execution_timer_middleware,
    secret_masking_middleware,
)

pipeline = (
    MiddlewarePipeline()
    .use(audit_logging_middleware(audit_log_sink))
    .use(execution_timer_middleware(lambda tid, ms: print(f"{tid} ran in {ms}ms")))
    .use(secret_masking_middleware(secret_keys={"api_key", "token", "password"}))
)

# Tasks executed through wrapped_runner will automatically have credentials redacted and timings logged:
instrumented_runner = pipeline.wrap_runner(base_task_runner)
```

### 31. Self-Healing Workflow Watchdog & Auto-Supervisor
Run a background watchdog that inspects active runs in SQLite for deadlocked, stalled, or zombie tasks (e.g. killed worker processes or unhandled kernel signals) and applies automated healing policies (`RETRY`, `ABORT_RUN`, `NOTIFY`):

```python
from orchestration_engine import AutoRemedy, SupervisorPolicy, WorkflowSupervisor

supervisor = WorkflowSupervisor(
    "workflows.db",
    SupervisorPolicy(stuck_timeout_seconds=60.0, default_remedy=AutoRemedy.RETRY, max_auto_retries=3),
)

# Inspects running workflows, resets stuck tasks to ready, or aborts permanently failing runs:
incidents = supervisor.scan_and_heal()
for inc in incidents:
    print(f"Healed task {inc.task_id} via {inc.remedy_applied}: {inc.reason}")
```

## Public API

| Name | Purpose |
| --- | --- |
| `Task`, `Workflow` | Core data models |
| `TaskResult` | Result returned by task runners containing `output` and `error` |
| `Hooks` | Post-persistence lifecycle event callbacks |
| `WorkflowBuilder` | Fluent builder for creating and validating workflows |
| `workflow_to_dict` | Serialize a `Workflow` into a JSON-compatible dict |
| `RetryPolicy` | Per-task retry configuration (max_attempts, delay_seconds) |
| `TaskState`, `WorkflowStatus` | State enums (`PENDING`, `READY`, `RUNNING`, `RETRY_WAIT`, `SUCCEEDED`, `FAILED`, `CANCELLED`) |
| `run_workflow` | Run an already-constructed `Workflow`; returns `run_id` |
| `run_workflow_from_file` | Load a JSON workflow file and run it end-to-end |
| `resume_run` | Resume an interrupted workflow run from SQLite |
| `load_workflow_from_json` | Parse JSON dict into a `Workflow` (with optional `collect_errors=True`) |
| `load_workflow_from_yaml` | Parse YAML workflow definition (requires `orchestration-engine[yaml]`) |
| `get_workflow_status` | Get a workflow's in-memory overall lifecycle status |
| `get_run_status` | Get run status derived directly from SQLite events |
| `get_workflow_history` | Retrieve ordered event log tuples for a workflow |
| `get_run_history` | Retrieve ordered event log tuples for a specific run |
| `list_runs` | List recorded runs newest first (optionally by workflow_id) |
| `get_connection` | Get or initialize SQLite connection with WAL & migrations |
| `run_workflow_async` | Native high-throughput asyncio DAG coordinator |
| `run_workflow_multiprocess` | Multi-process CPU-bound runner bypassing GIL |
| `task`, `workflow` | Functional decorators for authoring Python DAGs |
| `TaskCache` | Deterministic SQLite result memoization with TTL |
| `TokenBucketRateLimiter` | Thread-safe and async-safe token-bucket rate limiter |
| `CronSchedule`, `IntervalSchedule` | 5-field standard cron and interval schedule specifications |
| `WorkflowScheduler` | Recurring background daemon for scheduling workflows |
| `map_tasks`, `fan_in_task` | Dynamic parallel task fan-out and reduction |
| `SignalBroker`, `default_signal_broker` | Human-in-the-loop and external signal broker |
| `SignalTimeoutError` | Raised on signal expiration timeout |
| `TraceExporter`, `Span` | Chrome Trace (Perfetto) and OpenTelemetry W3C trace exporter |
| `force_complete_task` | Programmatically force/false-complete a task with synthetic fallback |
| `run_saga`, `SagaResult`, `SagaStatus` | Distributed Sagas with compensating transaction rollbacks |
| `CircuitBreaker`, `CircuitState`, `CircuitBreakerOpenError` | Persistent resilient circuit breaker for external services |
| `DeadLetterQueue`, `DeadLetterMessage`, `create_dlq_hook` | Dead Letter Queue for failed task capture, triage, and replay |
| `TaskLease`, `acquire_lease`, `renew_lease`, `release_lease`, `get_lease` | Distributed advisory mutual exclusion leasing without Redis |
| `evaluate_branch`, `apply_branch_decision`, `BranchDecision` | Dynamic decision tree evaluation and conditional path routing |
| `WatermarkStore`, `Watermark` | Stateful incremental ETL checkpoint and watermark store |
| `generate_execution_plan`, `ExecutionPlan`, `ExecutionStage` | Dry-run topological execution plan and critical path analyzer |
| `StateGraph`, `CompiledStateGraph`, `StateGraphResult`, `StateCheckpointer`, `START`, `END` | Cyclic state graph engine with reflection loops and thread checkpointing |
| `StreamPipe`, `run_streaming_pipeline` | Zero-memory chunked streaming with SQLite spill-to-disk spooling |
| `PriorityTaskQueue`, `TaskPriority` | Multi-priority scheduling and fair multi-tenant concurrency caps |
| `sandboxed`, `sandboxed_run`, `ResourceLimits` | Isolated subprocess runner with POSIX memory and CPU quotas |
| `CoordinatorServer`, `WorkerAgent` | Zero-dependency distributed HTTP cluster coordinator and worker agent |
| `TimerStore`, `DurableTimer`, `TimerStatus`, `create_sleep_marker` | SQLite-backed durable timers and workflow suspensions |
| `DataContract`, `Field`, `ContractValidationError`, `enforce_contract` | Zero-dependency runtime schema contracts and validation |
| `ChaosPolicy`, `ChaosInjector`, `ChaosFaultError`, `with_chaos` | Pluggable chaos engineering and deterministic fault injection |
| `WorkflowReplaySnapshot`, `time_travel_inspect`, `fork_run_from_task` | Historical time-travel inspection and checkpointed run forking |
| `WorkflowVersionRegistry`, `compute_workflow_hash`, `compare_workflows`, `MigrationPolicy` | Semantic workflow versioning and code drift migration policies |
| `IdempotencyStore`, `IdempotencyRecord`, `IdempotencyStatus`, `IdempotencyConflictError`, `idempotent` | Distributed exactly-once idempotency keys and state locking |
| `EventBus`, `Event`, `EventSubscription`, `WebhookServer` | Event-driven pub/sub bus with wildcard patterns and stdlib webhook server |
| `WorkflowBlackboard` | Transactional run-scoped KV blackboard with atomic CAS and increments |
| `SLAMonitor`, `SLAPolicy`, `SLABreachRecord` | Proactive SLA deadline tracking, threshold alerts, and breach escalation |
| `compact_event_log`, `export_cold_archive`, `vacuum_database` | Tiered archival, event compaction, and SQLite vacuum maintenance |
| `SubWorkflowResult`, `execute_subworkflow`, `make_subworkflow_runner`, `get_subworkflow_tree` | Hierarchical nested workflows with parent-child run trees |
| `compute_task_hash`, `IncrementalStore`, `IncrementalRunResult`, `wrap_incremental` | Content-addressable incremental task evaluation and caching |
| `AdaptiveConcurrencyPolicy`, `AdaptiveConcurrencyController` | AIMD adaptive concurrency control and system load backpressure |
| `BLOB_MARKER_KEY`, `BlobReference`, `BlobStore` | Content-addressed compressed blob offloading for large payloads |
| `CDCRun`, `CDCEvent`, `CDCOutput`, `CDCBatch`, `CDCReplicationSource`, `CDCReplicationTarget`, `ReplicationServer`, `ReplicationClient` | Multi-node SQLite replication and Change Data Capture (CDC) streaming |
| `WorkerNodeInfo`, `WorkStealingRegistry` | Distributed cluster work stealing, load rebalancing, and dead worker task reclamation |
| `CatchupPolicy`, `BackfillWindow`, `BackfillPlan`, `generate_backfill_plan`, `BackfillExecutor` | Historical backfill planning, anti-thundering-herd jitter, and deterministic interval execution |
| `TenantQuota`, `TenantUsage`, `TenantQuotaManager`, `TenantQuotaExceededError` | Multi-tenant concurrency limits, token-bucket rate limiting, and fair-share isolation |
| `TaskExecutionContext`, `Middleware`, `MiddlewarePipeline`, `secret_masking_middleware`, `execution_timer_middleware`, `audit_logging_middleware` | Composable onion task execution middleware, credential masking, duration timing, and audit logs |
| `AutoRemedy`, `ZombieTaskIncident`, `SupervisorPolicy`, `WorkflowSupervisor` | Self-healing watchdog, stuck/zombie task detection, and automatic remediation policies |
| `OrchestrationError` | Base exception for all engine errors |
| `WorkflowDefinitionError` | Raised on malformed workflow definitions (subclasses `ValueError`) |
| `WorkflowValidationError` | Raised on invalid workflow DAG structure (subclasses `ValueError`) |
| `PersistenceError` | Raised when persistence operations fail (wraps `sqlite3.Error`) |

## Authorship & Contact

- **Author / Maintainer:** Aditya Kumar ([adityakumarks2008@gmail.com](mailto:adityakumarks2008@gmail.com))
- **Development History:** The v0.1 core was hand-crafted; Stages 2–7 were developed via autonomous AI agent pairing with human code review and strict automated quality gates.

## License

Dual-licensed under either MIT or Apache 2.0 at your option — see [LICENSE-MIT](LICENSE-MIT) and [LICENSE](LICENSE).
