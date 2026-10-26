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

`orchestration-engine` includes a full-featured CLI for validating, executing, and inspecting workflows directly from the terminal:

```bash
# Validate workflow definition
orchestration-engine validate examples/simple_workflow.json

# Run workflow with an SQLite database
orchestration-engine run examples/simple_workflow.json --runner examples.runners:run --db workflows.db

# Inspect run status, transition history, and run list
orchestration-engine status <run_id> --db workflows.db
orchestration-engine history <run_id> --db workflows.db
orchestration-engine runs --db workflows.db
```

For full CLI documentation, exit codes, and JSON schemas, see [docs/cli.md](docs/cli.md).

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

- **[Multi-Step AI Agent Pipeline](examples/agent_pipeline.py)**: Orchestrates LLM tool calling, document retrieval, automated retries on transient API rate limits (`HTTP 429`), concurrent entity extraction, and fan-in executive summary synthesis.
- **[RAG Knowledge Ingestion & Vector Indexing](examples/rag_document_indexer.py)**: Semantic document chunking, parallel embedding generation with transient backpressure handling, vector store upsert, and an automated quality evaluation gate.
- **[Autonomous Incident Triage & Remediation](examples/incident_triage.py)**: SRE incident response workflow running parallel diagnostics across logs, metrics, and service dependencies (`max_concurrency=3`), synthesizing root cause analysis (RCA), executing automated remediation, and verifying health recovery.
- **[Resilient Data Flow & ETL](examples/data_flow.py)**: Producer-consumer data flow where task outputs pass cleanly downstream via `task.inputs` with full transactional persistence.

See the complete [Use Cases Documentation](docs/use-cases.md) for architectural diagrams and deep dives.

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
| `OrchestrationError` | Base exception for all engine errors |
| `WorkflowDefinitionError` | Raised on malformed workflow definitions (subclasses `ValueError`) |
| `WorkflowValidationError` | Raised on invalid workflow DAG structure (subclasses `ValueError`) |
| `PersistenceError` | Raised when persistence operations fail (wraps `sqlite3.Error`) |

## Authorship & Development

The v0.1 core was hand-crafted; Stages 2–7 were developed via autonomous AI agent pairing with human code review and strict automated quality gates.

## License

Dual-licensed under either MIT or Apache 2.0 at your option — see [LICENSE-MIT](LICENSE-MIT) and [LICENSE](LICENSE).
