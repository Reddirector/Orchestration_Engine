# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-25

### Added
- Complete production-grade release of Orchestration Engine with zero runtime dependencies.
- Production documentation suite built with MkDocs Material (`docs/`):
  - Architecture, concepts, quickstart, API reference, performance benchmarks, FAQ, and security policy.
- End-to-end multi-step AI Agent Pipeline example (`examples/agent_pipeline.py`) demonstrating rate-limit retry handling, fan-out/fan-in concurrency, and crash-resume.
- Benchmark suite in `benchmarks/` measuring scheduling overhead, SQLite event throughput, and concurrency scaling.
- Security and DoS protections: input size limits (`MAX_WORKFLOW_FILE_SIZE = 10MB`, `MAX_TASKS_PER_WORKFLOW = 5000`, `MAX_DEPENDENCIES_PER_TASK = 500`), 100% parameterized SQL queries, and safe YAML parsing.
- Frozen public API contract with strict SemVer and deprecation policy (`docs/policy.md`).
- Release verification automation (`scripts/verify_release.sh`) and GitHub Actions trusted publishing workflow (`.github/workflows/release.yml`).

### Behavior changes
- Public API frozen to 25 symbols.
- Development Status bumped to `5 - Production/Stable`.

## [0.6.0] - 2026-10-25

### Added
- Standard library `argparse` CLI: console script `orchestration-engine` and `python -m orchestration_engine`.
  - Commands: `validate`, `run`, `resume`, `status`, `history`, `runs`.
  - Exit code contract: `0` (succeeded), `1` (failed/cancelled), `2` (usage/definition error), `3` (database/internal error).
  - `--json` machine-readable output mode for all commands with stable schema.
  - Dynamic `--runner module:function` loader via `importlib.import_module` with current working directory prepended to `sys.path`.
- Structured logging:
  - Library logger `orchestration_engine` configured with `logging.NullHandler()` to avoid hijacking client application logging.
  - Transitions logged at `INFO`, retries and timeouts at `WARNING`, persistence failures at `ERROR`.
  - Structured `extra` fields: `workflow_id`, `run_id`, `task_id`, `old_state`, `new_state`, `attempt`.
  - CLI global `--log-level [DEBUG|INFO|WARNING|ERROR]` flag.
- Documentation: `docs/cli.md` complete CLI reference and JSON schemas, and ADR 014.
- `examples/runners.py`: Standard runners for CLI and examples.

### Behavior changes
- None to public library API (`orchestration_engine.__all__` remains frozen).

## [0.5.0] - 2026-10-25

### Added
- `TaskResult(ok: bool, output: Any = None, error: str | None = None)`: frozen dataclass allowing task runners to return output payloads.
- `Task.inputs: dict[str, Any]`: Automatically populated with upstream outputs `{dep_id: output}` prior to task dispatch.
- SQLite Schema v2: Added `task_outputs(run_id, task_id, output_json, error)` table with automatic migrations.
- `Hooks`: Safe post-persistence lifecycle callbacks (`on_task_start`, `on_task_succeeded`, `on_task_failed`, `on_task_retry`, `on_workflow_done`). Exceptions in hooks are safely caught and never disrupt execution.
- `WorkflowBuilder`: Ergonomic fluent builder for constructing and validating `Workflow` definitions.
- `workflow_to_dict`: Lossless serializer producing standard JSON-compatible dictionaries that round-trip with `load_workflow_from_json`.
- `workflow.schema.json`: Formal JSON Schema shipped as package data.
- Collect-errors loader: `load_workflow_from_json(..., collect_errors=True)` returns a `WorkflowDefinitionError` with an `.errors` list containing JSON-pointer paths for all schema violations.
- Optional YAML loading: `load_workflow_from_yaml` via optional extra `orchestration-engine[yaml]` using `yaml.safe_load`.
- Examples: `examples/data_flow.py`, `examples/hooks.py`, `examples/builder.py`.

### Behavior changes
- Database schema upgraded to v2 (`PRAGMA user_version = 2`), introducing the `task_outputs` table.
- Task runner can return either `bool` (legacy) or `TaskResult`.
- Outputs must be JSON-serializable; non-serializable outputs are treated as failed attempts with explanatory `last_error` rather than crashing the engine.

## [0.4.0] - 2026-10-25

### Added
- Concurrency control in `run_workflow`, `run_workflow_from_file`, and `resume_run`:
  - `max_concurrency: int = 1`: Allows executing independent ready tasks concurrently up to the configured limit.
  - `executor: Literal["thread", "process", "_inline"] = "thread"`: Selects execution backend.
- Single-Writer Coordinator:
  - Exclusive coordinator thread ownership of all SQLite operations and state transitions, guaranteeing zero thread contention or `sqlite3.ProgrammingError`.
- Process backend (`executor="process"`):
  - Uses `multiprocessing.get_context("spawn")`.
  - Enforces picklability check of `task_runner` before workflow execution starts.
  - On task timeout, worker child process is terminated with `SIGTERM` and forcefully killed with `SIGKILL` after a grace period.
  - Child crashes report exit code in `task.last_error` and enter standard retry/fail lifecycle.
- Internal `_inline` executor for deterministic testing with virtual clocks and fake sleep.

### Behavior changes
- Tasks can run in parallel up to `max_concurrency`. With `max_concurrency=1` and `executor="thread"`, execution order and behavior remain strictly backward compatible.

## [0.3.0] - 2026-10-25

### Behavior changes
- `run_workflow` returns the `run_id` as a string (was `None`).
- Single source of truth: Engine internals read `task.state` directly from `Task` models; `task_states` is maintained automatically as a mirror.
- Resumption after crash: Interrupted tasks in `RUNNING` status are recorded as failed attempts with `error = "interrupted: process exited while running"` and retried or failed per policy.
- Completed tasks in a resumed run are never re-executed.

### Added
- Database schema v1 with `PRAGMA user_version`: automatic migrations from v0, adding `run_id`, `next_retry_at`, and `error` columns to `task_events`.
- `runs` table tracking `run_id`, `workflow_id`, `started_at`, `finished_at`, `status`, and `definition_json`.
- Connection hardening: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000` for file databases.
- `resume_run`: Resumes interrupted workflow runs from SQLite.
- `get_run_status`: Derives workflow status of a run directly from database events.
- `get_run_history`: Retrieves event history tuples for a specific run.
- `list_runs`: Lists recorded runs newest first with optional `workflow_id` filtering.

## [0.2.0] - 2026-10-25

### Behavior changes
- Runner exceptions follow the retry policy: a `task_runner` callable that raises an exception is retried up to `task.retry_policy.max_attempts` instead of immediately transitioning to `FAILED` on attempt 1.
  - Before: `task_runner` exception immediately transitioned task to `FAILED` regardless of `max_attempts`, leaving `task_states` out of sync.
  - After: Exception enters `fail_task` retry path, transitions to `RETRY_WAIT` if attempts remain, syncs `task_states`, and sets `task.last_error = "ExceptionType: message"` (truncated to 2000 chars).
- Non-blocking timeouts: When a task times out, `run_workflow` detaches and moves on immediately without waiting for the worker thread to finish.
- Default timeout: `Task.timeout_seconds` now defaults to `30.0` seconds instead of `1` second. Explicit `None` disables the timeout. Workflows support `default_timeout_seconds`.
- Retry delay timestamp: `next_retry_at` and event timestamps are recorded from completion/failure time instead of pass start time.
- Transitive cancellation: Downstream dependents of CANCELLED or FAILED tasks are cancelled to a fixpoint across direct and transitive dependencies.
- Retry wait scheduling: `run_workflow` waits for tasks in `RETRY_WAIT` state instead of breaking the loop prematurely.
- Configurable database: `get_connection` accepts an explicit path or respects `ORCHESTRATION_ENGINE_DB`, supporting `":memory:"`.
- Sub-second precision and range validation: Seconds (`delay_seconds`, `timeout_seconds`) are floating-point; values are validated (`max_attempts >= 1`, delays/timeouts `>= 0`, booleans rejected).

### Added
- `Task.last_error`: Stores error message or timeout details (`"timeout after Ns"` or `"ExceptionType: message"`).
- `Workflow.default_timeout_seconds`: Optional workflow-level default timeout for tasks.
- Error hierarchy: `OrchestrationError`, `WorkflowDefinitionError`, `WorkflowValidationError`, `PersistenceError`.
- `run_workflow(..., sleep=...)`: Keyword parameter to inject custom sleep implementation for clock-advancing or test virtualization.

## [0.1.0] - 2026-09-26
- Initial release: sequential execution, retries with exponential backoff, timeouts, failure propagation, SQLite append-only event log, JSON workflow loader.
