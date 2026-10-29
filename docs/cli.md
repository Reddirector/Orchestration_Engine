# Command-Line Interface (CLI) Reference

The `orchestration-engine` package provides a standalone CLI tool for validating, executing, resuming, and inspecting workflow runs.

## Entry Points

The CLI can be invoked in two equivalent ways:

```bash
# As an installed console script
orchestration-engine <command> [options]

# As an executable Python module
python -m orchestration_engine <command> [options]
```

---

## Security & Runner Trust Model

The `run` and `resume` subcommands accept a `--runner module:function` flag.

> [!WARNING]
> Specifying `--runner` dynamically imports Python code via `importlib.import_module` and executes the specified callable. To resolve local modules, the current working directory (`os.getcwd()`) is prepended to `sys.path`.
>
> Running a workflow with `--runner` carries the **same trust level as executing a Python script**. Only pass runner paths from trusted sources.

---

## Exit Codes

All CLI commands follow strict, machine-parseable exit code contracts:

| Exit Code | Meaning | Description |
|---|---|---|
| `0` | **Success** | Workflow execution succeeded, or query/validation command succeeded. |
| `1` | **Workflow Failure** | Workflow ran to completion but finished with status `failed` or `cancelled`. |
| `2` | **Usage / Definition Error** | Invalid CLI arguments, schema validation failure, file not found, or run ID not found. |
| `3` | **Internal / Database Error** | Database connection/query failure (`PersistenceError`) or unhandled runtime error. |

---

## Subcommands

### 1. `validate`

Validates a workflow definition file against the formal workflow schema. Supports JSON files, or YAML files if the optional `yaml` extra is installed (`pip install 'orchestration-engine[yaml]'`).

```bash
orchestration-engine validate <workflow_file> [--json]
```

**JSON Schema (`--json`):**
```json
{
  "workflow_id": "wf-example-1",
  "tasks_count": 2,
  "valid": true
}
```

---

### 2. `run`

Executes a workflow to completion from a definition file.

```bash
orchestration-engine run <workflow_file> \
    --runner <module:function> \
    [--db <path>] \
    [--run-id <id>] \
    [--max-concurrency <N>] \
    [--executor <thread|process>] \
    [--json]
```

- `--runner`: (Required) Path to the task runner callable in `module:function` syntax.
- `--db`: Path to an SQLite database file. If omitted, an in-memory database is used.
- `--run-id`: Optional custom identifier for the run. If omitted, a UUID is generated.
- `--max-concurrency`: Maximum concurrent tasks (default: `1`).
- `--executor`: Concurrency backend: `thread` (default) or `process`.
- `--json`: Output machine-readable JSON summary.

**JSON Schema (`--json`):**
```json
{
  "run_id": "477fdb0e0b774caf85cf4b6f80c47432",
  "workflow_id": "wf-example-1",
  "status": "succeeded"
}
```

---

### 3. `resume`

Resumes an interrupted or partially-failed workflow run from its persisted database state.

```bash
orchestration-engine resume <run_id> \
    --runner <module:function> \
    --db <path> \
    [--max-concurrency <N>] \
    [--executor <thread|process>] \
    [--json]
```

- `--db`: (Required) Path to the SQLite database containing the persisted run.

**JSON Schema (`--json`):**
```json
{
  "run_id": "477fdb0e0b774caf85cf4b6f80c47432",
  "status": "succeeded"
}
```

---

### 4. `status`

Queries the current status of a workflow run from the database.

```bash
orchestration-engine status <run_id> --db <path> [--json]
```

**JSON Schema (`--json`):**
```json
{
  "run_id": "477fdb0e0b774caf85cf4b6f80c47432",
  "status": "succeeded"
}
```

---

### 5. `history`

Retrieves the complete state transition audit log for a run, ordered chronologically.

```bash
orchestration-engine history <run_id> --db <path> [--json]
```

**JSON Schema (`--json`):**
```json
[
  {
    "id": 1,
    "workflow_id": "wf-example-1",
    "task_id": "fetch-data",
    "old_state": "pending",
    "new_state": "ready",
    "timestamp": 1792930540.132,
    "attempt_count": 0
  },
  {
    "id": 2,
    "workflow_id": "wf-example-1",
    "task_id": "fetch-data",
    "old_state": "ready",
    "new_state": "running",
    "timestamp": 1792930540.133,
    "attempt_count": 1
  }
]
```

---

### 6. `runs`

Lists workflow runs stored in the database, ordered newest first.

```bash
orchestration-engine runs --db <path> [--workflow <workflow_id>] [--json]
```

- `--workflow`: Optional filter to list runs matching a specific workflow ID.

**JSON Schema (`--json`):**
```json
[
  {
    "run_id": "477fdb0e0b774caf85cf4b6f80c47432",
    "workflow_id": "wf-example-1",
    "started_at": 1792930540.132,
    "finished_at": 1792930540.134,
    "status": "succeeded"
  }
]
```

---

### 7. `plan`

Analyzes workflow structure and computes topological execution stages, critical path, and maximum parallelism without executing side effects.

```bash
orchestration-engine plan <file> [--json]
```

- `<file>`: (Required) Path to the workflow JSON or YAML file.
- `--json`: Format the execution plan output as structured JSON.

**Example:**
```bash
orchestration-engine plan workflow.json
```

**Output:**
```
Workflow: etl-pipeline
Total Tasks: 8
Max Parallelism: 4 concurrent workers
Critical Path: extract -> chunk -> embed -> index

Execution Stages:
  Stage 0: extract
  Stage 1: chunk_a, chunk_b, chunk_c, chunk_d
  Stage 2: embed
  Stage 3: index
```

---

### 8. `dlq`

Inspects and manages the persistent Dead Letter Queue (DLQ) for failed tasks.

```bash
orchestration-engine dlq <list|purge> [--db <path>] [--workflow <id>] [--limit <n>] [--older-than <sec>] [--json]
```

- `list`: View captured task failure messages, stack traces, and input payloads.
- `purge`: Delete captured failure messages matching filters.
- `--db`: Path to the SQLite database (defaults to `orchestration.db`).
- `--workflow`: Filter messages by workflow identifier.
- `--limit`: Maximum number of messages to list (default: 50).
- `--older-than`: Purge messages older than $N$ seconds.
- `--json`: Output as structured JSON.

---

### 9. `trace`

Exports run execution spans into Google Chrome Trace Event Format (compatible with `chrome://tracing` and [Perfetto UI](https://ui.perfetto.dev)).

```bash
orchestration-engine trace <run_id> --db <path> [-o trace.json]
```

- `run_id`: Workflow run identifier.
- `--db`: Path to the SQLite database.
- `-o, --output`: Optional output JSON file path (defaults to stdout).

---

### 10. `signal`

Delivers a human-in-the-loop approval or external webhook payload to a workflow run.

```bash
orchestration-engine signal <run_id> <signal_name> [--payload <json>] [--db <path>]
```

- `run_id`: Workflow run identifier.
- `signal_name`: Identifier of the signal (e.g. `approval`, `webhook`, `review`).
- `--payload`: JSON payload string (defaults to `{}`).
- `--db`: Path to the SQLite database.

---

## Observability & Logging

By default, the `orchestration_engine` library attaches a `NullHandler` to avoid hijacking parent application logs.

When running via the CLI, use the `--log-level` flag to enable structured standard logging:

```bash
orchestration-engine --log-level INFO run examples/simple_workflow.json --runner examples.runners:run
```

Supported log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`.

Structured log events emit structured `extra` fields:
- `workflow_id`: Workflow identifier
- `run_id`: Run identifier
- `task_id`: Task identifier
- `old_state`: Previous task state
- `new_state`: Next task state
- `attempt`: Current attempt counter
