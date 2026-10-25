# Frequently Asked Questions (FAQ)

### 1. When should I choose the Thread backend vs the Process backend?

- Use **Thread backend (`executor="thread"`)** for I/O-bound workflows such as HTTP requests, database queries, and AI model API calls. Threads have lower scheduling overhead and allow passing non-picklable in-memory objects.
- Use **Process backend (`executor="process"`)** when executing CPU-bound calculations, when isolating memory between worker tasks is required, or when hard termination of timed-out tasks (`SIGTERM` / `SIGKILL`) is essential.

---

### 2. How does resume work after a server crash?

When a process crashes or receives `SIGKILL`, incomplete tasks remain in `RUNNING` status in the SQLite database.

Upon calling `resume_run(conn, run_id, task_runner, ...)`:
1. The engine scans the database for the given `run_id`.
2. Tasks that were `RUNNING` are marked as interrupted attempts and transitioned to `RETRY_WAIT` (if attempts remain) or `FAILED`.
3. Already `SUCCEEDED` tasks are preserved and never re-executed; their stored outputs in `task_outputs` are re-injected into downstream tasks.
4. The coordinator resumes scheduling from the exact point of interruption.

---

### 3. How does the engine avoid SQLite lock errors under concurrency?

SQLite allows multiple readers but only one writer at any given moment. `orchestration-engine` uses a **single-writer architecture**:
- Worker threads and child processes execute user code only and never connect to SQLite.
- Only the main coordinator thread holds an SQLite connection and performs writes.
- SQLite is initialized with `PRAGMA journal_mode = WAL` and `PRAGMA busy_timeout = 5000`.
- As a result, `sqlite3.OperationalError: database is locked` cannot occur during normal execution.

---

### 4. Can tasks pass non-JSON data downstream?

Task outputs stored in the database via `TaskResult(ok=True, output=...)` must be JSON-serializable to ensure that runs can be safely persisted, inspected by the CLI, and resumed from disk across process restarts. If a runner returns non-JSON serializable output, the attempt fails with an explanatory error.

---

### 5. What happens if a lifecycle hook raises an exception?

Lifecycle hooks (`Hooks`) run immediately after state transitions have been committed to SQLite. Any exception raised by a hook callable is safely caught and suppressed by the engine (`_safe_call_hook`). This ensures that failures in metrics or notifications never corrupt internal state or disrupt pipeline execution.
