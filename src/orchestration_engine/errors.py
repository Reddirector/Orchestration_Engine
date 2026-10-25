"""
Error hierarchy for orchestration engine.
"""


class OrchestrationError(Exception):
    """Base class for all orchestration engine exceptions."""


class WorkflowDefinitionError(OrchestrationError, ValueError):
    """Raised when a workflow definition is invalid, incomplete, or malformed."""


class WorkflowValidationError(OrchestrationError, ValueError):
    """Raised when a workflow fails validation (cycles, invalid IDs, self-dependencies)."""


class PersistenceError(OrchestrationError):
    """Raised when a persistence or database operation fails."""
