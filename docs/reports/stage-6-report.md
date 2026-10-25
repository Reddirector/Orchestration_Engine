# Stage 6 Quality Gate Report: CLI and Observability (v0.6.0)

**Date**: 2026-10-25
**Branch**: `stages-2-7`
**Status**: PASSED

## Deliverables Checklist

- [x] **6.1 CLI**: Stdlib `argparse` only, zero runtime dependencies. Registered `orchestration-engine` console script in `pyproject.toml` and `python -m orchestration_engine` (`__main__.py`). Subcommands: `validate`, `run`, `resume`, `status`, `history`, `runs`. Testable `main(argv: list[str] | None = None) -> int` entry point.
- [x] **6.2 Contract**: Strict exit codes: `0` (success), `1` (workflow failed/cancelled), `2` (usage or definition error), `3` (database or internal error). Stable machine-readable `--json` schema output for all subcommands. `--runner module:function` dynamic loading via `importlib.import_module` with current working directory prepended to `sys.path`.
- [x] **6.3 Structured Logging**: Library logger `orchestration_engine` with `logging.NullHandler()` attached by default. Structured events emitted at `INFO` for state transitions, `WARNING` for retries and timeouts, and `ERROR` for persistence failures, with structured `extra` fields (`workflow_id`, `run_id`, `task_id`, `old_state`, `new_state`, `attempt`). Global CLI `--log-level` flag.
- [x] **6.4 Tests**: Comprehensive CLI test suite (`tests/test_cli.py`) testing every command, every exit code (0, 1, 2, 3), JSON schema validations, console script subprocess execution, and structured log records capture.
- [x] **6.5 Release**: Documentation in `docs/cli.md`, updated `README.md` and `CHANGELOG.md`, ADR 014, bumped version to `0.6.0`, gate passed with 147 tests and 91.44% coverage, tagged `stage-6-done`.

## Architectural Decision Records (ADRs)
- [ADR 014: Command-Line Interface and Structured Logging Architecture](../decisions/014-cli-and-structured-logging.md)

## Quality Gate Execution Output

```
=== 1. Checking Ruff ===
All checks passed!
=== 2. Checking Mypy ===
Success: no issues found in 33 source files
=== 3. Running Pytest with Coverage ===
........................................................................ [ 48%]
........................................................................ [ 97%]
...                                                                      [100%]
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.13-final-0 _______________

Name                                      Stmts   Miss  Cover
-------------------------------------------------------------
src/orchestration_engine/__init__.py         15      2    87%
src/orchestration_engine/__main__.py          4      0   100%
src/orchestration_engine/builder.py          39      0   100%
src/orchestration_engine/cli.py             244     23    91%
src/orchestration_engine/errors.py            7      0   100%
src/orchestration_engine/executor.py         37      4    89%
src/orchestration_engine/loader.py          138      5    96%
src/orchestration_engine/models.py           54      0   100%
src/orchestration_engine/persistence.py      96      8    92%
src/orchestration_engine/readiness.py        57      4    93%
src/orchestration_engine/runner.py          336     51    85%
src/orchestration_engine/scheduler.py        13      0   100%
src/orchestration_engine/status.py           35      1    97%
src/orchestration_engine/transitions.py      36      0   100%
src/orchestration_engine/validation.py       46      1    98%
-------------------------------------------------------------
TOTAL                                      1157     99    91%
Required test coverage of 90% reached. Total coverage: 91.44%
147 passed in 6.39s
=== 4. Building Wheel ===
Building source distribution (uv build backend)...
Building wheel from source distribution (uv build backend)...
Successfully built dist/orchestration_engine-0.6.0.tar.gz
Successfully built dist/orchestration_engine-0.6.0-py3-none-any.whl
=== 5. Testing Fresh Venv Wheel Installation & Exports ===
All 25 exports successfully imported from wheel
=== 6. Running Examples Against Installed Wheel ===
Running examples/builder.py...
Executed workflow successfully with run_id: 5a97b19c4d254e7680dd155c74e37b1c
Running examples/data_flow.py...
Workflow completed successfully! run_id: dbc54114858d42eea23cb73118f630c4
Running examples/hooks.py...
Run 899fb98cb7f84746948926ffea50cee2 complete.
Running examples/runners.py...
Running examples/run_simple_workflow.py...
Workflow finished with status: succeeded
=== 7. Checking Clean Working Tree ===
=== Quality Gate Passed Successfully! ===
```

## Stage 6 Acceptance Verification
Verified in clean isolated virtual environment from built wheel:
```bash
$ orchestration-engine run examples/simple_workflow.json --runner examples.runners:run --db /tmp/stage6_acc.db
Executing task: Fetch data (fetch-data)
Executing task: Process data (process-data)
Workflow run 'ab3db5d5241a41c6b26685607f883ea3' completed with status: succeeded

$ orchestration-engine status ab3db5d5241a41c6b26685607f883ea3 --db /tmp/stage6_acc.db
Run ab3db5d5241a41c6b26685607f883ea3: succeeded

$ orchestration-engine history ab3db5d5241a41c6b26685607f883ea3 --db /tmp/stage6_acc.db
[1792931192.64] Task 'fetch-data': pending -> ready (attempt 0)
[1792931192.64] Task 'fetch-data': ready -> running (attempt 1)
[1792931192.64] Task 'fetch-data': running -> succeeded (attempt 1)
[1792931192.64] Task 'process-data': pending -> ready (attempt 0)
[1792931192.64] Task 'process-data': ready -> running (attempt 1)
[1792931192.64] Task 'process-data': running -> succeeded (attempt 1)

$ orchestration-engine runs --db /tmp/stage6_acc.db
ab3db5d5241a41c6b26685607f883ea3  workflow=wf-example-1  status=succeeded  started=1792931192.6360157  finished=1792931192.6373389
```
All commands succeeded with documented exit codes (`0`).
