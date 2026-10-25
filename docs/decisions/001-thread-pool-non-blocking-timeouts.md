# ADR 001: Non-Blocking Task Timeouts in Coordinator

## Context
In v0.1.0, task execution wrapped individual tasks inside `with ThreadPoolExecutor(max_workers=1) as pool:`. When a task exceeded its `timeout_seconds`, `future.result(timeout=...)` raised `TimeoutError`, but exiting the `with` block blocked the engine until the underlying thread finished execution. Consequently, a hung task with a 1-second timeout blocked the entire engine for the full duration of the hung task.

## Decision
Replace the blocking context manager with an explicit `ThreadPoolExecutor`. When a timeout or task completion occurs, call `pool.shutdown(wait=False, cancel_futures=True)` in a `finally` block. Because Python threads cannot be preemptively killed from outside without terminating the process, the task thread will continue in the background, but the engine coordinator immediately marks the task failed and proceeds with scheduling other tasks.

## Consequences
- Engine scheduling is no longer blocked by slow or hung tasks.
- Background threads continue running until completion or process termination, which is documented as a known Python runtime constraint.
