# ADR 014: Command-Line Interface and Structured Logging Architecture

## Context
Operators and automation pipelines require a command-line interface to inspect, validate, run, and resume workflows without writing Python driver scripts. Additionally, observability requires structured logging without imposing unwanted logging configurations on embedded library users.

## Options Considered
1. **Third-party CLI frameworks (e.g. Click, Typer, Rich)**:
   - *Tradeoff*: Violates the zero-runtime-dependencies core design philosophy.
2. **Standard library `argparse` and `logging.NullHandler` (Chosen)**:
   - Provide CLI entry points via `[project.scripts] orchestration-engine = "orchestration_engine.cli:main"` and `python -m orchestration_engine`.
   - Implement commands: `validate`, `run`, `resume`, `status`, `history`, `runs`.
   - Contracted exit codes: `0` (succeeded), `1` (workflow failed), `2` (usage/definition error), `3` (internal error).
   - Stable machine-readable `--json` output for automation scripts.
   - Dynamic runner resolution via `importlib.import_module` with current working directory prepended to `sys.path`.
   - Library logger `orchestration_engine` configured with `NullHandler()`. Transitions logged at INFO, retries/timeouts at WARNING, database errors at ERROR, with structured `extra` fields. CLI enables global logging only when `--log-level` is explicitly provided.

## Decision
- Build `orchestration_engine.cli` using `argparse`.
- Add `orchestration_engine/__main__.py`.
- Configure `logging.NullHandler()` on library logger in `__init__.py`.
- Document CLI contracts and exit codes in `docs/cli.md`.

## Consequences
- Zero runtime dependencies maintained.
- Standardized exit codes and JSON output allow reliable pipeline automation.
- Safe library logging avoids hijacking client application logging configurations.
