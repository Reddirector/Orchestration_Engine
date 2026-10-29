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
| `OrchestrationError` | Base exception for all engine errors |
| `WorkflowDefinitionError` | Raised on malformed workflow definitions (subclasses `ValueError`) |
| `WorkflowValidationError` | Raised on invalid workflow DAG structure (subclasses `ValueError`) |
| `PersistenceError` | Raised when persistence operations fail (wraps `sqlite3.Error`) |

## Authorship & Contact

- **Author / Maintainer:** Aditya Kumar ([adityakumarks2008@gmail.com](mailto:adityakumarks2008@gmail.com))
- **Development History:** The v0.1 core was hand-crafted; Stages 2–7 were developed via autonomous AI agent pairing with human code review and strict automated quality gates.

## License

Dual-licensed under either MIT or Apache 2.0 at your option — see [LICENSE-MIT](LICENSE-MIT) and [LICENSE](LICENSE).
