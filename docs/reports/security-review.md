# Comprehensive Security Audit & Review

**Date**: 2026-10-25
**Scope**: Codebase audit against Stage 7.4 security requirements
**Status**: PASSED — All checks verified with automated tests in `tests/test_security.py`

---

## 1. Parameterized SQL Audit

Every SQL statement across the entire codebase was audited for parameterization. **100% of dynamic queries use `?` parameter placeholders.** There is zero string concatenation, f-string formatting, or `%` interpolation in any SQL query.

### Complete Inventory of SQL Statements

| File & Line | Operation | Statement / Query Pattern | Parameterization |
|---|---|---|---|
| `persistence.py:19` | Metadata | `PRAGMA user_version` | Constant |
| `persistence.py:24` | Schema Check | `SELECT name FROM sqlite_master WHERE type='table' AND name='task_events'` | Constant |
| `persistence.py:30` | Schema Check | `PRAGMA table_info(task_events)` | Constant |
| `persistence.py:33-37` | Migration v1 | `ALTER TABLE task_events ADD COLUMN run_id TEXT` (and next_retry_at, error) | Constant |
| `persistence.py:38` | Migration v1 | `UPDATE task_events SET run_id = 'legacy_run_0' WHERE run_id IS NULL` | Constant |
| `persistence.py:42` | Migration v1 | `INSERT OR IGNORE INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) SELECT DISTINCT ...` | Constant |
| `persistence.py:59` | Schema Init | `CREATE TABLE IF NOT EXISTS task_events (...)` | Constant |
| `persistence.py:71-73` | Schema Init | `CREATE INDEX ...`, `PRAGMA user_version = 1` | Constant |
| `persistence.py:77` | Migration v2 | `CREATE TABLE IF NOT EXISTS task_outputs (...)` | Constant |
| `persistence.py:89-92` | Migration v2 | `CREATE INDEX ...`, `PRAGMA user_version = 2` | Constant |
| `persistence.py:110` | Output Save | `INSERT INTO task_outputs (run_id, task_id, output_json, error) VALUES (?, ?, ?, ?) ON CONFLICT(...) DO UPDATE ...` | `(run_id, task_id, output_json, error)` |
| `persistence.py:134` | Output Fetch | `SELECT task_id, output_json FROM task_outputs WHERE run_id = ? AND output_json IS NOT NULL` | `(run_id,)` |
| `persistence.py:171-175` | PRAGMAs | `PRAGMA foreign_keys = ON`, `PRAGMA busy_timeout = 5000`, `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL` | Constant |
| `persistence.py:222` | Audit Log | `INSERT INTO task_events (workflow_id, task_id, old_state, new_state, timestamp, attempt_count, run_id, next_retry_at, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)` | 9 positional parameters |
| `persistence.py:263` | Audit Query | `SELECT id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count FROM task_events WHERE workflow_id = ? ORDER BY timestamp, id` | `(workflow_id,)` |
| `persistence.py:284` | Audit Query | `SELECT id, workflow_id, task_id, old_state, new_state, timestamp, attempt_count FROM task_events WHERE run_id = ? ORDER BY timestamp, id` | `(run_id,)` |
| `persistence.py:306` | Run Query | `SELECT run_id, workflow_id, started_at, finished_at, status FROM runs WHERE workflow_id = ? ORDER BY started_at DESC` | `(workflow_id,)` |
| `persistence.py:316` | Run Query | `SELECT run_id, workflow_id, started_at, finished_at, status FROM runs ORDER BY started_at DESC` | Constant |
| `runner.py:211` | Run Record | `INSERT INTO runs (run_id, workflow_id, started_at, finished_at, status, definition_json) VALUES (?, ?, ?, NULL, 'running', ?) ON CONFLICT ...` | `(actual_run_id, workflow.workflow_id, started_at, definition_json)` |
| `runner.py:279` | Run Complete | `UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?` | `(finished_at, final_status, actual_run_id)` |
| `runner.py:818` | Resume Fetch | `SELECT definition_json FROM runs WHERE run_id = ?` | `(run_id,)` |
| `runner.py:834` | Resume State | `SELECT task_id, new_state FROM task_events WHERE run_id = ? ORDER BY timestamp ASC, id ASC` | `(run_id,)` |
| `status.py:45` | Status Fetch | `SELECT definition_json FROM runs WHERE run_id = ?` | `(run_id,)` |
| `status.py:57` | Status Calc | `SELECT task_id, new_state FROM task_events WHERE run_id = ? ORDER BY timestamp ASC, id ASC` | `(run_id,)` |

---

## 2. Path and Runner Trust Model

- **Finding**: The `--runner module:function` CLI option dynamically imports user modules and executes Python code.
- **Remediation**: The security boundary is explicitly documented in `SECURITY.md`, `docs/cli.md`, and inline docstrings. Executing `--runner` carries the same trust model as executing an arbitrary Python script. Operators must restrict input to trusted runner paths.

---

## 3. Safe Loading for Definitions (JSON & YAML)

- **JSON Loading**: Standard `json.loads` is used. Unknown fields are ignored during execution to ensure forward compatibility, while `collect_errors=True` checks standard JSON schema types.
- **YAML Loading**: Only `yaml.safe_load` is utilized in `loader.py`. Arbitrary Python object deserialization via YAML tags is prohibited. Verified via `tests/test_security.py::test_yaml_safe_load_blocks_arbitrary_code`.

---

## 4. Size, Depth, and Resource Exhaustion Limits

- **Workflow File Size**: Enforced limit of **10 MB** (`MAX_WORKFLOW_FILE_SIZE`). Files exceeding 10 MB are rejected immediately before reading or parsing. Verified via `tests/test_security.py::test_file_size_limit_json`.
- **Workflow Task Count**: Enforced limit of **5,000 tasks** (`MAX_TASKS_PER_WORKFLOW`). Verified via `tests/test_security.py::test_workflow_task_count_limit`.
- **Task Dependencies Count**: Enforced limit of **500 dependencies per task** (`MAX_DEPENDENCIES_PER_TASK`). Verified via `tests/test_security.py::test_task_dependencies_count_limit`.

---

## 5. Pickle Serialization Scope

- **Audit**: `pickle` usage was audited across the entire codebase.
- **Result**: `pickle` is used exclusively in `src/orchestration_engine/runner.py` for IPC over unidirectional pipes in `multiprocessing.get_context("spawn")`. It is never used for database persistence, file loading, or thread execution.

---

## 6. Supply Chain & Dependencies

- **Core Runtime Dependencies**: 0 (zero runtime third-party dependencies).
- **Development Tooling**: Development dependencies (`mypy`, `pytest`, `pytest-cov`, `ruff`, `pyyaml`, `mkdocs`, `mkdocs-material`) are pinned and managed strictly via `pyproject.toml` and locked in `uv.lock`.
