# Quickstart

This guide demonstrates defining a workflow, executing it in Python, and inspecting the resulting database audit log.

## 1. Define a Workflow

Workflows can be defined in JSON, YAML, or programmatically using `WorkflowBuilder`.

### Option A: JSON Definition (`workflow.json`)

```json
{
  "workflow_id": "wf-quickstart",
  "name": "Data Pipeline",
  "description": "Fetch, transform, and load pipeline",
  "default_timeout_seconds": 30.0,
  "tasks": [
    {
      "task_id": "fetch",
      "name": "Fetch API Data",
      "description": "Retrieves remote records",
      "dependencies": [],
      "retry_policy": {
        "max_attempts": 3,
        "delay_seconds": 1.0
      },
      "timeout_seconds": 15.0
    },
    {
      "task_id": "process",
      "name": "Process Records",
      "description": "Transforms retrieved records",
      "dependencies": ["fetch"],
      "retry_policy": {
        "max_attempts": 1,
        "delay_seconds": 0.0
      },
      "timeout_seconds": 30.0
    }
  ]
}
```

### Option B: Programmatic Fluent Builder

```python
from orchestration_engine import WorkflowBuilder, RetryPolicy

workflow = (
    WorkflowBuilder("wf-quickstart", "Data Pipeline")
    .description("Fetch, transform, and load pipeline")
    .default_timeout(30.0)
    .add_task(
        "fetch",
        name="Fetch API Data",
        retry_policy=RetryPolicy(max_attempts=3, delay_seconds=1.0),
        timeout_seconds=15.0,
    )
    .add_task(
        "process",
        name="Process Records",
        dependencies=["fetch"],
    )
    .build()
)
```

---

## 2. Implement the Task Runner

A task runner is a callable that accepts a `Task` and returns either a `bool` (legacy) or a `TaskResult`:

```python
from orchestration_engine import Task, TaskResult

def task_runner(task: Task) -> TaskResult:
    print(f"Executing: {task.name} ({task.task_id})")
    
    if task.task_id == "fetch":
        # Return output payload to downstream tasks
        return TaskResult(ok=True, output={"records": [1, 2, 3]})
        
    elif task.task_id == "process":
        # Upstream outputs are automatically injected in task.inputs
        records = task.inputs["fetch"]["records"]
        total = sum(records)
        return TaskResult(ok=True, output={"total": total})

    return TaskResult(ok=False, error="Unknown task")
```

---

## 3. Run the Workflow

```python
import time
from orchestration_engine import get_connection, run_workflow, get_run_status

# Open or create SQLite persistence database
conn = get_connection("pipeline.db")

# Run workflow
run_id = run_workflow(
    workflow=workflow,
    task_states={},
    time_source=time.time,
    task_runner=task_runner,
    conn=conn,
    max_concurrency=2,
)

# Check run status
status = get_run_status(conn, run_id)
print(f"Run {run_id} finished with status: {status.value}")
```

---

## 4. Inspecting via the CLI

You can inspect the resulting database using the CLI:

```bash
# View run status
orchestration-engine status <run_id> --db pipeline.db

# View transition audit history
orchestration-engine history <run_id> --db pipeline.db

# List all recorded runs
orchestration-engine runs --db pipeline.db
```
