# Core Concepts

This section provides an in-depth reference for the engine's scheduling, state management, fault-tolerance mechanisms, and persistence.

---

## Task Lifecycle and States

Each task within a workflow exists in one of seven well-defined states:

```
            +-------------+
            |   PENDING   |
            +------+------+
                   |
         +---------+---------+
         |                   | (dependency failure)
         v                   v
     +-------+         +-----------+
     | READY |         | CANCELLED |
     +---+---+         +-----------+
         |
         v
    +---------+
    | RUNNING |
    +----+----+
         |
    +----+-------------------+
    |            |           |
    v            v           v
+-----------+ +------------+ +--------+
| SUCCEEDED | | RETRY_WAIT | | FAILED |
+-----------+ +-----+------+ +--------+
                    |
                    v (delay expires)
                +-------+
                | READY |
                +-------+
```

| State | Description |
|---|---|
| `PENDING` | Initial state. Waiting for upstream dependencies to complete. |
| `READY` | All direct upstream dependencies have completed with `SUCCEEDED`. Task is eligible for dispatch. |
| `RUNNING` | Task has been assigned to an active worker thread or child process. |
| `SUCCEEDED` | Task runner returned success (`True` or `TaskResult(ok=True)`). Terminal state. |
| `RETRY_WAIT` | Task failed an attempt, but remaining attempts exist. Waiting for next retry deadline. |
| `FAILED` | Task exhausted all configured retry attempts. Terminal state. |
| `CANCELLED` | An upstream dependency failed or was cancelled. Dependent task is pruned. Terminal state. |

---

## Scheduling and Readiness

Scheduling operates on a Directed Acyclic Graph (DAG):
1. **DAG Validation**: On workflow initialization or load, cycle detection (`get_workflow_validation_error`) ensures there are no circular dependencies and all dependency IDs exist.
2. **Readiness Evaluation**: A task transitions from `PENDING` to `READY` if and only if **every** task ID in its `dependencies` list is currently in `SUCCEEDED` state.
3. **Execution Ordering**: Ready tasks are dispatched as worker slots become available up to `max_concurrency`.

---

## Retries and Exponential Backoff

When a task fails (by returning `False`, returning `TaskResult(ok=False)`, raising an unhandled exception, or timing out):
- If `attempt_count < retry_policy.max_attempts`:
  - The task transitions to `RETRY_WAIT`.
  - The next retry timestamp is calculated using exponential backoff:
    $$\text{delay} = \text{delay\_seconds} \times 2^{\text{attempt\_count} - 1}$$
  - The coordinator sleeps until the earliest pending `RETRY_WAIT` deadline before checking for ready tasks.
- If `attempt_count >= retry_policy.max_attempts`:
  - The task transitions to `FAILED`.

---

## Failure Propagation & Transitive Cancellation

When a task transitions to `FAILED`, any downstream task depending on it cannot succeed. 

To maintain workflow integrity without hanging:
1. All direct dependents of a failed or cancelled task are transitioned to `CANCELLED`.
2. The cancellation algorithm runs to a **fixpoint** inside `schedule_once`, ensuring transitive dependents (e.g. `A -> B -> C`) are cancelled immediately within the same iteration.
3. Independent DAG branches are unaffected and continue running to completion.

---

## Timeouts

Every task can specify a `timeout_seconds: float | None` (defaulting to 30.0s, or the workflow's `default_timeout_seconds`):
- In the **Thread backend**: When a task exceeds its deadline, the coordinator marks the attempt timed out, schedules a retry or failure, and abandons the worker future.
- In the **Process backend**: The coordinator terminates the child process (`SIGTERM`), waits for a brief grace period, and forcefully kills (`SIGKILL`) if unresponsive.

---

## Data Flow & Task Outputs

Tasks can pass structured data downstream:
- Return `TaskResult(ok=True, output={...})` from a task runner.
- The output payload is validated as JSON-serializable and written to the SQLite `task_outputs` table.
- Before executing a downstream task, the engine populates `task.inputs` with a dictionary mapping each dependency's `task_id` to its produced output:
  ```python
  # In task 'calculate_tax' which depends on 'get_cart':
  cart = task.inputs["get_cart"]
  ```

---

## Lifecycle Hooks

Lifecycle hooks allow applications to observe workflow execution without polling or mutating engine state:
- `on_task_start(task: Task)`: Invoked when a task enters `RUNNING`.
- `on_task_succeeded(task: Task)`: Invoked after a task completes successfully.
- `on_task_failed(task: Task)`: Invoked after a task exhausts retries and enters `FAILED`.
- `on_task_retry(task: Task)`: Invoked when a task attempt fails and enters `RETRY_WAIT`.
- `on_workflow_done(workflow: Workflow, status: WorkflowStatus)`: Invoked after all tasks reach terminal states.

All hooks are executed post-persistence. Any unhandled exception within a hook is caught and suppressed, guaranteeing that observer failures cannot crash workflow execution.
