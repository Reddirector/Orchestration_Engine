# Architecture

`orchestration-engine` is designed around a single-writer architecture with strict separation of concerns across small internal modules.

```
                    +-----------------------------+
                    |       Public Client         |
                    | (run_workflow, resume_run)  |
                    +--------------+--------------+
                                   |
                                   v
                    +-----------------------------+
                    |         Coordinator         |
                    |   (Single-Writer Loop)      |
                    +--------------+--------------+
                                   |
         +-------------------------+-------------------------+
         |                         |                         |
         v                         v                         v
+-----------------+       +-----------------+       +-----------------+
|   Readiness &   |       |  Worker Pool    |       |  Transitions &  |
|    Scheduler    |       | (Thread/Process)|       |   Persistence   |
+-----------------+       +-----------------+       +-----------------+
                                                             |
                                                             v
                                                    +-----------------+
                                                    | SQLite Database |
                                                    |  (WAL Mode)     |
                                                    +-----------------+
```

---

## Single-Writer SQLite Pattern

SQLite offers exceptional durability and zero-configuration storage, but concurrent multi-threaded writes can trigger `sqlite3.OperationalError: database is locked`.

To eliminate SQLite locking issues completely:
1. **Exclusive Coordinator Ownership**: Worker threads and child processes **never** interact with the SQLite database.
2. **Write-Ahead Transitions**: The coordinator thread owns the SQLite connection. Before any in-memory state transition is applied, it writes the transition to the `task_events` audit table.
3. **Connection Settings**:
   - `PRAGMA journal_mode = WAL`: Write-Ahead Logging allows concurrent readers alongside writers.
   - `PRAGMA synchronous = NORMAL`: Balances ACID guarantees with write speed.
   - `PRAGMA foreign_keys = ON`: Enforces relational integrity across tables.
   - `PRAGMA busy_timeout = 5000`: 5-second automatic retry on internal lock contention.

---

## Execution Backends

Workflows support three execution backends configured via `executor`:

### 1. Thread Backend (`executor="thread"`)
- Backed by standard library `ThreadPoolExecutor`.
- Low overhead, ideal for I/O-bound tasks (HTTP calls, database queries, LLM API calls).
- On timeout: the worker thread future is abandoned by the coordinator. Python threads cannot be forcefully killed without native thread primitives.

### 2. Process Backend (`executor="process"`)
- Uses `multiprocessing.get_context("spawn")` for complete memory and interpreter isolation.
- Ideal for CPU-intensive tasks, untrusted user code, or tasks requiring true process termination.
- Communicates task outputs and errors via unidirectional `multiprocessing.Pipe`.
- On timeout: worker child process receives `SIGTERM`, followed by `SIGKILL` after a 0.2s grace period.
- Requires that `task_runner` and inputs/outputs are picklable.

### 3. Inline Backend (`executor="_inline"`)
- Internal deterministic execution backend used for testing.
- Single-threaded, synchronous execution with fake time sources.

---

## Internal Module Map

| Module | Responsibility |
|---|---|
| `models.py` | Core dataclasses: `Task`, `Workflow`, `RetryPolicy`, `TaskResult`, `Hooks`, `TaskState`, `WorkflowStatus`. |
| `readiness.py` | DAG dependency checks: determines ready tasks and detects blocked/cancelled tasks. |
| `scheduler.py` | `schedule_once` evaluation: advances ready tasks and cancels blocked dependents to a fixpoint. |
| `executor.py` | Task lifecycle dispatch: `execute_task`, `complete_task`, `fail_task`, `retry_task`. |
| `transitions.py` | State machine enforcement: validates legal state transitions and writes event logs. |
| `persistence.py` | SQLite schema migrations (v0 -> v1 -> v2), connection factory, and audit log queries. |
| `runner.py` | Coordinator loops (`_run_coordinator_thread`, `_run_coordinator_process`), timeout checking, retry sleep. |
| `status.py` | Status derivation: computes overall workflow status from in-memory or persisted task states. |
| `validation.py` | DAG cycle detection and configuration schema validation. |
| `loader.py` | File deserialization: loads workflows from JSON with JSON-pointer error collection, or YAML. |
| `builder.py` | Fluent `WorkflowBuilder` and round-trip `workflow_to_dict` serializer. |
| `cli.py` | Command-line interface subcommands (`validate`, `run`, `resume`, `status`, `history`, `runs`). |
