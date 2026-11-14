# Guard Verification Notes

Recorded versions pinned in `pyproject.toml` and `uv.lock`:

- `call4agents`: **0.7.2** (latest on PyPI, installed and verified; auto-registers pytest plugin `call4agents`)
- `agentraas`: **0.16.0** (installed and verified)
- `idempotent-tools`: **0.1.1** (installed and verified)

### pytest plugin: `call4agents`
- Entry-point: `call4agents = call4agents.pytest_plugin`
- Functionality: Provides pytest test fixtures/hooks for tracing agent steps and recording tool invocations during test runs.
- Compatibility verification: Tested with `-p no:call4agents` and with plugin enabled. All test suites run identically and pass.
