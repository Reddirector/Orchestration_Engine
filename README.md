# Orchestration-Engine

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

Not yet published to PyPI. Install directly from source for now:

```bash
pip install git+https://github.com/Reddirector/Orchestration_Engine.git
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

## Public API

| Name | Purpose |
| --- | --- |
| `Task`, `Workflow` | Core data models |
| `RetryPolicy` | Per-task retry configuration (max_attempts, delay_seconds) |
| `TaskState`, `WorkflowStatus` | State enums (`PENDING`, `READY`, `RUNNING`, `RETRY_WAIT`, `SUCCEEDED`, `FAILED`, `CANCELLED`) |
| `run_workflow` | Run an already-constructed `Workflow`; returns `run_id` |
| `run_workflow_from_file` | Load a JSON workflow file and run it end-to-end |
| `resume_run` | Resume an interrupted workflow run from SQLite |
| `load_workflow_from_json` | Parse JSON dict into a `Workflow` with validation |
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

## License

Apache 2.0 — see [LICENSE](LICENSE).
