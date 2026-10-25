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
- Timestamps measured from completion: `next_retry_at` and event timestamps are recorded from completion/failure time instead of pass start time.

### Added
- `Task.last_error`: Stores error message or timeout details (`"timeout after Ns"` or `"ExceptionType: message"`).

## [0.1.0] - 2026-09-26
- Initial release: sequential execution, retries with exponential backoff, timeouts, failure propagation, SQLite append-only event log, JSON workflow loader.
