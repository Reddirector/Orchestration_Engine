# ADR 013: Optional YAML Support via PyYAML Extra

## Context
Many users and workflow authors prefer YAML for human readability. However, parsing YAML requires third-party dependencies (e.g. PyYAML), which would compromise the engine's core zero-runtime-dependency commitment.

## Options Considered
1. **Require PyYAML as a mandatory runtime dependency**:
   - *Tradeoff*: Violates the zero-runtime-dependencies promise for users only using JSON or Python programmatic builders.
2. **Optional extra `orchestration-engine[yaml]` with lazy import (Chosen)**:
   - Core library remains 100% dependency-free.
   - Introduce `load_workflow_from_yaml` which imports `yaml` lazily on call.
   - If `yaml` is missing, raise a clear `OrchestrationError` instructing the user to install `orchestration-engine[yaml]`.
   - Always parse with `yaml.safe_load` to prevent arbitrary code execution vulnerabilities.

## Decision
- Add optional dependency `yaml = ["pyyaml>=6.0"]` in `pyproject.toml`.
- Provide `load_workflow_from_yaml` in `loader.py`.
- Export `load_workflow_from_yaml` in `orchestration_engine.__all__`.

## Consequences
- Core stays dependency-free; users wanting YAML install the optional extra safely.
- Safe YAML parsing prevents deserialization security attacks.
