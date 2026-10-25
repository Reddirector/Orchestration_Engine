# API Reference

Complete reference for all public classes, functions, enums, and exceptions exported by `orchestration_engine`.

---

## Models & Data Structures

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

## Execution & Persistence Functions

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
Executes a workflow to completion and returns the executed `run_id`.

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
Loads a workflow from a JSON file and executes it, returning the final `WorkflowStatus`.

### `resume_run`
```python
def resume_run(
    conn: sqlite3.Connection,
    run_id: str,
    task_runner: Callable[[Task], bool | TaskResult],
    time_source: Callable[[], float],
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_concurrency: int = 1,
    executor: Literal["thread", "process", "_inline"] = "thread",
    hooks: Hooks | None = None,
) -> WorkflowStatus:
```
Resumes an interrupted or partially-failed run from SQLite.

### `get_connection`
```python
def get_connection(db_path: str = ":memory:") -> sqlite3.Connection:
```
Creates and configures an SQLite connection with WAL journal mode, busy timeouts, and schema migrations.

### `get_run_status`
```python
def get_run_status(conn: sqlite3.Connection, run_id: str) -> WorkflowStatus:
```
Derives the current `WorkflowStatus` of a run directly from the database.

### `get_run_history`
```python
def get_run_history(conn: sqlite3.Connection, run_id: str) -> list[tuple[Any, ...]]:
```
Returns every task transition event recorded for a specific run ID.

### `get_workflow_status`
```python
def get_workflow_status(workflow: Workflow) -> WorkflowStatus:
```
Computes the overall workflow status from in-memory task states.

### `get_workflow_history`
```python
def get_workflow_history(conn: sqlite3.Connection, workflow_id: str) -> list[tuple[Any, ...]]:
```
Returns all historical transition events recorded for a workflow ID across all runs.

### `list_runs`
```python
def list_runs(conn: sqlite3.Connection, workflow_id: str | None = None) -> list[tuple[Any, ...]]:
```
Lists run summaries `(run_id, workflow_id, started_at, finished_at, status)` from the database.

---

## Builders & Loaders

### `WorkflowBuilder`
Fluent builder for defining workflows with validation.
- `WorkflowBuilder(workflow_id: str, name: str)`
- `.description(desc: str) -> WorkflowBuilder`
- `.default_timeout(seconds: float | None) -> WorkflowBuilder`
- `.task(task_id: str, name: str, dependencies: list[str] = ..., retry_policy: RetryPolicy = ..., timeout_seconds: float | None = ...) -> WorkflowBuilder`
- `.build() -> Workflow`

### `workflow_to_dict`
```python
def workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
```
Serializes a `Workflow` into a JSON-compatible dictionary.

### `load_workflow_from_json`
```python
def load_workflow_from_json(json_data: dict[str, Any], *, collect_errors: bool = False) -> Workflow:
```
Parses a dictionary into a `Workflow`.

### `load_workflow_from_yaml`
```python
def load_workflow_from_yaml(source: str | os.PathLike[str] | Any, *, collect_errors: bool = False) -> Workflow:
```
Parses a YAML string, file path, or stream into a `Workflow` (requires `orchestration-engine[yaml]`).

---

## Exceptions

- `OrchestrationError`: Base exception for all errors raised by the engine.
- `WorkflowValidationError`: Raised when DAG validation fails (cycles, missing dependencies, invalid timeouts/concurrency).
- `WorkflowDefinitionError`: Raised when workflow definitions fail schema validation or contain malformed JSON/YAML.
- `PersistenceError`: Raised when SQLite operations encounter a database error or file failure.
