# ADR 007: Task vs TaskRun Internal Representation

## Context
A classic architectural decision in workflow orchestrators is whether to introduce a separate `TaskRun` dataclass representing a specific execution attempt of a `Task`, or to maintain `Task` as the state container updated in-place with historical transitions preserved in SQLite.

## Decision
Retain `Task` as the primary lifecycle object during execution, rather than introducing a public `TaskRun` abstraction:
1. `Task` encapsulates the current in-flight state, `attempt_count`, and `last_error`.
2. Every state transition and attempt is immutably logged to `task_events` tagged with `run_id`, `timestamp`, and `attempt_count`.
3. An internal `_run_id` attribute on `Task` links tasks to their run context without widening public constructor contracts.
4. Engine scheduling reads `task.state` as the single source of truth, eliminating desynchronization between in-memory structures and dictionaries.

## Consequences
- The public API surface remains minimal, clean, and backwards-compatible.
- Detailed execution history is fully preserved in SQLite for querying, replay, and resumption.
