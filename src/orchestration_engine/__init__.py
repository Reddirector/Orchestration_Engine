import importlib.metadata

from .errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowDefinitionError,
    WorkflowValidationError,
)
from .loader import load_workflow_from_json, run_workflow_from_file
from .models import RetryPolicy, Task, TaskState, Workflow, WorkflowStatus
from .persistence import get_connection, get_workflow_history
from .runner import run_workflow
from .status import get_workflow_status

try:
    __version__ = importlib.metadata.version("orchestration-engine")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.2.0"

__all__ = [
    "__version__",
    "Task",
    "Workflow",
    "RetryPolicy",
    "TaskState",
    "WorkflowStatus",
    "run_workflow",
    "run_workflow_from_file",
    "load_workflow_from_json",
    "get_workflow_status",
    "get_workflow_history",
    "get_connection",
    "OrchestrationError",
    "WorkflowDefinitionError",
    "WorkflowValidationError",
    "PersistenceError",
]
