# Stage 3 Quality Gate Report: Durability, Runs and Resume (v0.3.0)

**Date**: 2026-10-25
**Branch**: `stages-2-7`
**Status**: PASSED

## Deliverables Checklist

- [x] **3.1 Schema v1 and runs**: `PRAGMA user_version = 1`, migrations from v0, `runs` table, indexes, `get_run_history` (`322ef84`)
- [x] **3.2 Connection hardening**: WAL mode, NORMAL sync, foreign keys, busy timeout 5000ms (`db76de7`)
- [x] **3.3 run_id plumbing**: `run_id` generation, tracking runs, tagging task_events, returning `run_id` (`284e757`)
- [x] **3.4 Status from database**: `get_run_status` derived from events, `list_runs` newest first (`46011fe`)
- [x] **3.5 G6 single source of truth**: Internal scheduling reads `task.state` directly; `task_states` mirror synced (`39dcc1c`)
- [x] **3.6 Resume**: `resume_run` with state restoration, handling RUNNING tasks as failed attempts, no re-executing SUCCEEDED tasks (`02f5daf`)
- [x] **3.7 Crash test**: Subprocess SIGKILL and resume verification test (`b9d50a4`)
- [x] **3.8 Docs and release**: ADRs 004-007, updated README & CHANGELOG, bump to `0.3.0`

## Architectural Decision Records (ADRs)
- [ADR 004: Schema v1 Migration and Runs Table](../decisions/004-schema-v1-and-runs-table.md)
- [ADR 005: Run Model and Lifecycle Tracking](../decisions/005-run-model-and-lifecycle.md)
- [ADR 006: Crash Recovery and Resume Semantics](../decisions/006-resume-semantics.md)
- [ADR 007: Task vs TaskRun Internal Representation](../decisions/007-task-vs-taskrun-representation.md)

## Quality Gate Execution Output

```
=== 1. Checking Ruff ===
All checks passed!
=== 2. Checking Mypy ===
Success: no issues found in 27 source files
=== 3. Running Pytest with Coverage ===
........................................................................ [ 90%]
........                                                                 [100%]
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover
-------------------------------------------------------------
src/orchestration_engine/__init__.py         12      2    83%
src/orchestration_engine/errors.py            4      0   100%
src/orchestration_engine/executor.py         34      4    88%
src/orchestration_engine/loader.py           54      2    96%
src/orchestration_engine/models.py           39      0   100%
src/orchestration_engine/persistence.py      66      5    92%
src/orchestration_engine/readiness.py        57      4    93%
src/orchestration_engine/runner.py          108      5    95%
src/orchestration_engine/scheduler.py        13      0   100%
src/orchestration_engine/status.py           35      1    97%
src/orchestration_engine/transitions.py      31      0   100%
src/orchestration_engine/validation.py       46      2    96%
-------------------------------------------------------------
TOTAL                                       499     25    95%
Required test coverage of 90% reached. Total coverage: 94.99%
80 passed in 1.74s
=== 4. Building Wheel ===
Building source distribution (uv build backend)...
Building wheel from source distribution (uv build backend)...
Successfully built dist/orchestration_engine-0.3.0.tar.gz
Successfully built dist/orchestration_engine-0.3.0-py3-none-any.whl
=== 5. Testing Fresh Venv Wheel Installation & Exports ===
All 20 exports successfully imported from wheel
=== 6. Running Examples Against Installed Wheel ===
Running examples/run_simple_workflow.py...
Running task: Fetch data (fetch-data)
Running task: Process data (process-data)
Workflow finished with status: succeeded
=== 7. Checking Clean Working Tree ===
=== Quality Gate Passed Successfully! ===
```
