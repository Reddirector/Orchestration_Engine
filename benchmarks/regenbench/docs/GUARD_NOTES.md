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

## Empirical 10-line Experiment: idempotent-tools 0.1.1
- API setup: `@idempotent(backend=SQLiteBackend(db_path=...), key_fn=..., context=...)`.
- `default_key_fn` behavior:
  Hashes `func.__name__` + JSON-serialized args/kwargs. If `context` is supplied, it salts the hash: `sha256(f"{context}:{digest}")`.
- Observation:
  1. Default keying (`G3a`): Identical calls return cached output. Drifted calls (`10` vs `10.0`) yield different JSON serialization, producing different hash digests and re-executing (total calls = 2).
  2. With `context=` (`G3b`): Because `default_key_fn` salts the argument digest rather than replacing it, argument drift still changes the digest unless a custom `key_fn` (e.g. key on `context` alone) is supplied. Documented workaround test will include `key_fn=lambda f, a, kw, ctx: str(ctx)`.

## Empirical Experiment: agentraas 0.16.0
- Package inspection:
  Exposes `protect(...)` and `Client(...)`.
  Requires an `agentraas_key` to connect to a proxy gateway (`base_url` default or self-hosted) which communicates via Redis to coordinate deduplication slots.
  For local hermetic benchmarking without cloud API keys, `G2` adapter simulates the server/client deduplication rule (exact request hash, SQLite/in-process store) and can connect to a local mock gateway endpoint if configured.

## Guard Freezing and Held-Out Set
- **Guard Freeze Point:** Guards `G4` (IntentGuard), `G5` (StepKey), and `G7` (SemanticAnalyzer) were frozen at commit `9e7efc1` on 2026-11-15 (tagged `guards-frozen` / `guards-frozen-v2` at `3e02ac8`). Subsequent commits only adjusted documented workaround adapters (`G1_workaround`, `G3b`) to extract business identifiers.
- **Held-Out Mutator Set (D6):** The D6 held-out mutator set and 3 new variants per D1-D5 (`heldout_mutators.py`) were authored on 2026-11-15 (commit `28c7b75` in the benchmark repository, integrated in commit `48248e3`).

## Documented Workaround Configurations
- **G1_workaround (`call4agents`):** Uses explicit `c4a_key` set to the business identifier (`order_id`, `to`, `customer_id`), bypassing volatile reference fields or numeric format drift.
- **G3b (`idempotent-tools`):** Configured with custom `key_fn` that extracts the business identifier (`order_id`, `to`, `customer_id`) rather than hashing the full argument payload.

