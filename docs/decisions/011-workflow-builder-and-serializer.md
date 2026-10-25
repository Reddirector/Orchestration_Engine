# ADR 011: WorkflowBuilder and workflow_to_dict Serializer

## Context
Defining workflows programmatically via raw dataclass instantiations (`Task`, `RetryPolicy`, `Workflow`) is verbose, error-prone, and doesn't validate DAG properties until execution time. Furthermore, serializing an in-memory `Workflow` back to standard JSON was not exported.

## Options Considered
1. **Direct dataclass construction only**: Keep relying solely on `Workflow(...)` and `Task(...)`.
   - *Tradeoff*: Lacks a fluent API, allows deferred validation errors.
2. **Fluent `WorkflowBuilder` and `workflow_to_dict` (Chosen)**:
   - `WorkflowBuilder`: Fluent builder chaining `.task(...)`, `.description(...)`, `.build()`.
   - Validation upon build: `.build()` immediately runs DAG validation and raises `WorkflowValidationError` if dependencies are broken or cycles exist.
   - `workflow_to_dict`: Serializes a `Workflow` into a JSON-compatible dictionary matching the engine schema and round-tripping with `load_workflow_from_json`.

## Decision
- Implement `WorkflowBuilder` in `src/orchestration_engine/builder.py`.
- Implement `workflow_to_dict` in `src/orchestration_engine/builder.py`.
- Export `WorkflowBuilder` and `workflow_to_dict` in `orchestration_engine.__all__`.

## Consequences
- Clean, ergonomic programmatic API for defining workflows in Python.
- Exact round-trip fidelity between dictionary representations and Workflow domain objects.
