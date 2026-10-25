"""
Error hierarchy for orchestration engine.
"""


class OrchestrationError(Exception):
    """Base class for all orchestration engine exceptions."""


class WorkflowDefinitionError(OrchestrationError, ValueError):
    """Raised when a workflow definition is invalid, incomplete, or malformed."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = list(errors or [])


class WorkflowValidationError(OrchestrationError, ValueError):
    """Raised when a workflow fails validation (cycles, invalid IDs, self-dependencies)."""


class PersistenceError(OrchestrationError):
    """Raised when a persistence or database operation fails."""
