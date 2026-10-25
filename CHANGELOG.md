# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
