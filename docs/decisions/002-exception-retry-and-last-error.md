# ADR 002: Exception Handling and Retry Path Unification

## Context
In v0.1.0, when a `task_runner` threw an unhandled exception, `run_workflow` caught it and immediately transitioned the task to `TaskState.FAILED` directly via `transition_task`. This bypassed `fail_task`, ignoring the configured `retry_policy.max_attempts`, leaving `task_states` stale (still `READY`), and losing the exception details.

## Decision
Route exceptions through `fail_task`, the same path taken when `task_runner` returns `False`. If attempts remain below `max_attempts`, the task enters `TaskState.RETRY_WAIT` with exponential backoff.
Store the error on `Task.last_error` as `"ExceptionType: message"` (truncated to 2000 characters). For timeouts, store `"timeout after Ns"`.

## Consequences
- Exceptions are retried like transient failures.
- `task_states` remains synchronized with `task.state`.
- Diagnostic failure details are captured on the task for inspection and history logs.
