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

## Public API

| Name | Purpose |
| --- | --- |
| `Task`, `Workflow` | Core data models |
| `RetryPolicy` | Per-task retry configuration (max_attempts, delay_seconds) |
| `TaskState`, `WorkflowStatus` | State enums (`PENDING`, `READY`, `RUNNING`, `RETRY_WAIT`, `SUCCEEDED`, `FAILED`, `CANCELLED`) |
| `run_workflow` | Run an already-constructed `Workflow` with optional `sleep` injection |
| `run_workflow_from_file` | Load a JSON workflow file and run it end-to-end |
| `load_workflow_from_json` | Parse JSON dict into a `Workflow` with validation |
| `get_workflow_status` | Get a workflow's overall lifecycle status |
| `get_workflow_history` | Retrieve ordered event log tuples for a workflow |
| `get_connection` | Get or initialize SQLite connection (explicit path, env var, or default) |
| `OrchestrationError` | Base exception for all engine errors |
| `WorkflowDefinitionError` | Raised on malformed workflow definitions (subclasses `ValueError`) |
| `WorkflowValidationError` | Raised on invalid workflow DAG structure (subclasses `ValueError`) |
| `PersistenceError` | Raised when persistence operations fail (wraps `sqlite3.Error`) |

## License

Apache 2.0 — see [LICENSE](LICENSE).
