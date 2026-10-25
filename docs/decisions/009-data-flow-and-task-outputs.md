# ADR 009: Data Flow, Task Outputs, and Schema v2

## Context
Orchestrating multi-step AI pipelines and general computational DAGs requires passing data between tasks (e.g. retrieval steps feeding extraction steps). In v0.1.0-v0.4.0, task runners returned a boolean indicating success or failure without returning output data.

## Options Considered
1. **Side-channel shared state / Context object**: Pass a mutable shared dictionary or context object to every task runner.
   - *Tradeoff*: Prone to race conditions under concurrency, non-deterministic, and breaks isolation between independent branches.
2. **Explicit Dependency Data Flow (`TaskResult` & `Task.inputs`) (Chosen)**:
   - Task runners can return `bool` (legacy compatibility) or a frozen `TaskResult(ok: bool, output: Any = None, error: str | None = None)`.
   - The engine automatically collects outputs from completed dependency tasks and injects them into `task.inputs: dict[str, Any]` before task dispatch.
   - Outputs are persisted as JSON in SQLite (`task_outputs` table) under Schema v2.
   - On crash or workflow resumption, inputs are reconstructed from persisted outputs.

## Decision
- Introduce `TaskResult(ok: bool, output: Any = None, error: str | None = None)` in `models.py`.
- Add `Task.inputs: dict[str, Any] = field(default_factory=dict)` as the final field of `Task`.
- Upgrade SQLite schema to v2 (`PRAGMA user_version = 2`), adding `task_outputs(run_id, task_id, output_json, error)`.
- Require outputs to be JSON-serializable; non-serializable outputs are treated as failed attempts with explanatory `last_error` rather than crashing the engine.
- Reconstruct outputs on `resume_run` so upstream data remains available to downstream tasks after interruptions.

## Consequences
- Full backward compatibility: runners returning `bool` continue to work unchanged.
- Clean, deterministic data flow with persistent auditability and crash recovery.
- Safe serialization boundary: prevents storing arbitrary unpicklable objects or breaking database schema.
