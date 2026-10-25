# Contributing to Orchestration Engine

Thank you for contributing to Orchestration Engine!

## Development Philosophy

- **Zero runtime dependencies**: The engine depends strictly on the Python standard library.
- **Correctness and durability**: Correct state persistence and error handling take precedence over raw speed.
- **Strict quality standards**: All code must pass `ruff`, `mypy --strict`, and maintain high test coverage.

## Setting Up Your Environment

This repository uses `uv` for dependency and virtual environment management:

```bash
# Clone the repository
git clone https://github.com/Reddirector/Orchestration_Engine.git
cd Orchestration_Engine

# Run test suite
uv run pytest

# Check formatting and linting
uv run ruff check

# Run strict type checking
uv run mypy
```

## Running the Quality Gate

Before submitting a pull request, run the quality gate script:

```bash
bash scripts/gate.sh
```

Ensure that:
1. `uv run ruff check` produces 0 errors.
2. `uv run mypy` produces 0 errors across `src` and `tests`.
3. Test suite passes with >=90% coverage.
4. No unexpected SQLite files (e.g. `orchestration.db`) are left in the repository.
5. `CHANGELOG.md` is updated under `[Unreleased]`.
