# ADR 012: JSON Schema and Collect-Errors Validation

## Context
External systems and authoring tools need a formal JSON Schema to validate workflow files ahead of time. Additionally, developer ergonomics are significantly degraded when a loader fails on only one error at a time (forcing multiple compile/run cycles to fix multiple syntax or schema mistakes).

## Options Considered
1. **Third-party schema validation library (e.g. `jsonschema`)**:
   - *Tradeoff*: Violates the zero-runtime-dependencies core design philosophy.
2. **Built-in JSON Schema asset + native collect-errors validation (Chosen)**:
   - Package a formal JSON Schema (`src/orchestration_engine/workflow.schema.json`) that can be used by external IDEs, YAML/JSON language servers, or test tooling.
   - Implement `load_workflow_from_json(data, *, collect_errors: bool = False)` natively in Python standard library.
   - When `collect_errors=False` (default): preserve exact fail-fast behavior.
   - When `collect_errors=True`: accumulate all definition errors with JSON-pointer paths (e.g. `/tasks/0/retry_policy/max_attempts`) and raise a single `WorkflowDefinitionError` with an `.errors` list.
   - Ignore unknown keys and allow `$schema` for forward compatibility.

## Decision
- Ship `workflow.schema.json` within package data.
- Add `collect_errors: bool = False` to `load_workflow_from_json`.
- Attach `errors: list[str]` attribute to `WorkflowDefinitionError`.

## Consequences
- Zero runtime dependencies preserved.
- Full tooling compatibility and comprehensive validation error reporting in a single pass.
