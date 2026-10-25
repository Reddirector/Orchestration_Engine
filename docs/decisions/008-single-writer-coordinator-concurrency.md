# ADR 008: Single-Writer Coordinator Architecture for Concurrency

## Context
Adding concurrent task execution introduces concurrency hazards with SQLite (which requires careful cross-thread connection sharing) and risks violating Invariant 1 (write-ahead logging must persist state before mutating in-memory models).

## Options Considered
1. **Multi-Writer Threads**: Each worker thread receives a shared or thread-local SQLite connection and performs its own state transitions directly.
   - *Tradeoff*: High risk of `sqlite3.ProgrammingError`, database locks/busy errors, race conditions in status evaluation, and complex distributed state coordination.
2. **Single-Writer Coordinator (Chosen)**: The main coordinator thread (calling `run_workflow`) retains sole ownership of:
   - All state transitions (`transition_task`).
   - All SQLite database reads, writes, and migrations.
   - All scheduling decisions and readiness calculations.
   Workers (threads or processes) are pure execution engines executing only the user-provided `task_runner(task)` callable and returning a lightweight completion result `(ok: bool, exception: BaseException | None)`.

## Decision
Adopt the **Single-Writer Coordinator** model:
- The coordinator maintains an active pool of in-flight tasks up to `max_concurrency`.
- As tasks complete or time out, worker outcomes are returned to the coordinator.
- The coordinator performs write-ahead database persistence and advances task lifecycles sequentially.
- No SQLite connection is ever passed to or touched by worker threads or child processes.

## Consequences
- Invariant 1 (write-ahead log before mutating state) remains strictly preserved.
- Complete thread-safety and SQLite isolation with zero database contention.
- Clean separation between execution (user logic) and orchestration (scheduling & persistence).
