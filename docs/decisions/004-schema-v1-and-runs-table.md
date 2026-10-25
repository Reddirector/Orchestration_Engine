# ADR 004: Schema v1 Migration and Runs Table

## Context
In v0.1.0/v0.2.0, the SQLite database had an unversioned `task_events` table lacking run isolation. Repeated runs of a workflow with the same `workflow_id` interleaved events in the same audit stream without distinction. Additionally, connection options (WAL mode, timeouts) were unconfigured.

## Decision
1. Introduce schema versioning using SQLite's `PRAGMA user_version = 1`.
2. Add columns `run_id TEXT`, `next_retry_at REAL`, and `error TEXT` to `task_events`.
3. Provide automated, transactional, and idempotent migration (`_migrate_database`) from version 0 to version 1:
   - Assign legacy events `run_id = 'legacy-' || workflow_id`.
   - Create `runs(run_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, status TEXT NOT NULL, definition_json TEXT NOT NULL)`.
   - Create indexes on `task_events(run_id, id)` and `task_events(workflow_id)`.
4. Configure connection pragmas for file databases: `journal_mode = WAL`, `synchronous = NORMAL`, `foreign_keys = ON`, `busy_timeout = 5000` (skipping WAL for `:memory:`).

## Consequences
- Every run is isolated and searchable by `run_id`.
- Backwards compatibility is preserved for v0 databases and test fixtures.
- Concurrent reads and writes to SQLite file databases are robust against locking timeouts.
