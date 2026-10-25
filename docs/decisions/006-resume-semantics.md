# ADR 006: Crash Recovery and Resume Semantics

## Context
Long-running workflows (especially multi-step AI pipelines) can experience abrupt process termination (e.g. host reboot, SIGKILL, container eviction). The engine needs to resume execution without re-executing already completed work or leaving tasks stuck in transient states.

## Decision
1. Implement `resume_run(conn, run_id, task_runner, time_source, *, sleep=time.sleep)`:
   - If the run is already in a terminal status (`SUCCEEDED` or `FAILED`), return its status immediately without invoking the runner.
   - Reconstruct the `Workflow` object by deserializing `definition_json` stored in the `runs` record.
   - Restore each task's latest state, `attempt_count`, and `next_retry_at` by scanning `task_events` for the run.
   - For any task left in `RUNNING` status (the process died while running it), treat it as an interrupted attempt: set `task.last_error = "interrupted: process exited while running"` and invoke `fail_task` to transition it to `RETRY_WAIT` or `FAILED` according to its retry policy.
   - Resume the normal scheduling loop via `run_workflow`. Tasks in `SUCCEEDED` status are never re-executed.

## Consequences
- Workflows are fully resilient against unexpected process crashes.
- Interrupted tasks respect their configured retry policies and failure tracking.
