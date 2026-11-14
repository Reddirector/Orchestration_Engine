# Guard Verification Notes

Recorded versions pinned in `pyproject.toml` and `uv.lock`:

- `call4agents`: **0.7.2** (latest on PyPI, installed and verified; auto-registers pytest plugin `call4agents`)
- `agentraas`: **0.16.0** (installed and verified)
- `idempotent-tools`: **0.1.1** (installed and verified)

### pytest plugin: `call4agents`
- Entry-point: `call4agents = call4agents.pytest_plugin`
- Functionality: Provides pytest test fixtures/hooks for tracing agent steps and recording tool invocations during test runs.
- Compatibility verification: Tested with `-p no:call4agents` and with plugin enabled. All test suites run identically and pass.

## Empirical 10-line Experiment: call4agents 0.7.2
- API setup: `call4agents.init(path=...)`, `with call4agents.run(run_id):`, and `@call4agents.effect`.
- Observation:
  1. Identical call (`charge('ord_1', 10)` twice within same `run_id`): cached on retry (0 secondary executions).
  2. Drifted argument (`charge('ord_1', 10.0)`): treated as a brand new action and executed a second time (total executions = 2).
- Result: Directly confirms documented limit. `call4agents` default keying keys on exact arguments.
