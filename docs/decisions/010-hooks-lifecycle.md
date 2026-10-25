# ADR 010: Lifecycle Hooks Architecture

## Context
Users, monitoring systems, and tracing tools need to observe workflow and task lifecycle events (task start, success, failure, retry, workflow completion).

## Options Considered
1. **Interceptor middleware**: Allow hooks to intercept and mutate state or abort execution.
   - *Tradeoff*: Fragile; user errors in hooks can corrupt state or break engine invariants.
2. **Safe post-persistence event hooks (Chosen)**:
   - Hooks are called strictly *after* matching database transactions and event logging succeed.
   - Any exception raised inside a hook callable is caught and safely suppressed (logged to standard logging), preventing user hook bugs from interrupting workflow execution or modifying task state.

## Decision
- Introduce `Hooks` dataclass in `models.py` with optional callables:
  - `on_task_start: Callable[[Task], None] | None = None`
  - `on_task_succeeded: Callable[[Task], None] | None = None`
  - `on_task_failed: Callable[[Task], None] | None = None`
  - `on_task_retry: Callable[[Task], None] | None = None`
  - `on_workflow_done: Callable[[Workflow, WorkflowStatus], None] | None = None`
- Pass `hooks: Hooks | None = None` to `run_workflow`, `run_workflow_from_file`, and `resume_run`.
- Add `Hooks` to the public API exports in `orchestration_engine`.

## Consequences
- Zero blast radius: raising hooks cannot crash workflows.
- Clean separation between workflow logic, engine state, and observability.
