# Orchestration-Engine

<!-- title placeholder — update once the project is named -->

A fault-tolerant workflow orchestration engine. Define tasks with dependencies, retry policies, and timeouts as JSON; the engine handles scheduling, execution ordering, retries, and state persistence — you supply the logic for each task.

## Features

- Dependency-based task scheduling (tasks run only once their dependencies succeed)
- Configurable per-task retry policies with delay
- Per-task timeouts
- SQLite-backed persistence of task state transitions and workflow history
- Workflows defined declaratively as JSON

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
  "tasks": [
    {
      "task_id": "fetch-data",
      "name": "Fetch data",
      "description": "Pulls input data",
      "dependencies": [],
      "retry_policy": { "max_attempts": 3, "delay_seconds": 5 },
      "timeout_seconds": 30
    },
    {
      "task_id": "process-data",
      "name": "Process data",
      "description": "Processes the fetched data",
      "dependencies": ["fetch-data"],
      "retry_policy": { "max_attempts": 3, "delay_seconds": 5 },
      "timeout_seconds": 30
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
    # Your actual logic goes here — call an LLM, hit an API, run a tool, etc.
    # Return True on success, False on failure (triggers retry per the task's retry_policy).
    return True

conn = get_connection()
status = run_workflow_from_file("workflow.json", task_runner, time.time, conn)
print(status)  # WorkflowStatus.SUCCEEDED
```

## Public API

| Name                          | Purpose                                          |
| ----------------------------- | ------------------------------------------------ |
| `Task`, `Workflow`            | Core data models                                 |
| `RetryPolicy`                 | Per-task retry configuration                     |
| `TaskState`, `WorkflowStatus` | State enums                                      |
| `run_workflow`                | Run an already-constructed `Workflow` object     |
| `run_workflow_from_file`      | Load a JSON workflow file and run it end-to-end  |
| `load_workflow_from_json`     | Parse JSON into a `Workflow` without running it  |
| `get_workflow_status`         | Get a workflow's current overall status          |
| `get_workflow_history`        | Get the ordered event log for a workflow         |
| `get_connection`              | Get/initialize the SQLite persistence connection |

Full parameter-level docs are in each function's docstring (see step 5 of the plan).

## License

Apache 2.0 — see [LICENSE](LICENSE).
