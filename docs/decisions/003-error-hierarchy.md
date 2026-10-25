# ADR 003: Orchestration Engine Error Hierarchy

## Context
v0.1.0 raised generic standard library exceptions (principally `ValueError`) for malformed workflow JSON, dependency cycles, duplicate task IDs, and raw `sqlite3.Error` on database failures. Callers had no type-safe way to catch engine-specific errors.

## Decision
Introduce a structured exception hierarchy under `OrchestrationError`:
- `WorkflowDefinitionError(OrchestrationError, ValueError)`: Raised by `loader.py` when definitions lack required keys or have invalid types.
- `WorkflowValidationError(OrchestrationError, ValueError)`: Raised by `runner.py` when workflow DAGs contain cycles, self-dependencies, or missing dependencies.
- `PersistenceError(OrchestrationError)`: Raised when SQLite operations fail during connection creation, state transition writes, or history retrieval, chaining `from e` to preserve original DB error contexts.

Subclassing `ValueError` for definition and validation errors preserves backward compatibility with existing exception handlers.

## Consequences
- Callers can catch specific orchestration errors or catch `OrchestrationError` broadly.
- Existing code catching `ValueError` continues to function uninterrupted.
- Database errors do not leak implementation-specific SQLite details unless explicitly inspected via `__cause__`.
