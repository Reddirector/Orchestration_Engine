# ADR 005: Run Model and Lifecycle Tracking

## Context
Orchestrating workflow executions across multiple attempts and invocations requires distinguishing between the workflow definition (intent) and execution instances (runs).

## Decision
1. Add an optional keyword-only `run_id: str | None = None` parameter to `run_workflow` and `run_workflow_from_file`.
2. If `run_id` is omitted, generate `uuid.uuid4().hex`.
3. `run_workflow` returns the `run_id` as a string (was `None`), providing an additive API change.
4. Record run start and terminal completion in the `runs` table, including start/finish timestamps, final status, and serialized workflow definition JSON.
5. Provide query functions `get_run_status(conn, run_id)` and `list_runs(conn, workflow_id=None)` returning runs ordered newest first.

## Consequences
- Callers can trace specific runs end-to-end.
- Run status can be queried directly from SQLite even without holding in-memory workflow instances.
