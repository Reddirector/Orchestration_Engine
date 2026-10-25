import importlib.metadata

from .errors import (
    OrchestrationError,
    PersistenceError,
    WorkflowDefinitionError,
    WorkflowValidationError,
)
from .loader import load_workflow_from_json, run_workflow_from_file
from .models import Hooks, RetryPolicy, Task, TaskResult, TaskState, Workflow, WorkflowStatus
from .persistence import get_connection, get_run_history, get_workflow_history, list_runs
from .runner import resume_run, run_workflow
from .status import get_run_status, get_workflow_status

try:
    __version__ = importlib.metadata.version("orchestration-engine")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.4.0"

__all__ = [
    "__version__",
    "Task",
    "TaskResult",
    "Workflow",
    "RetryPolicy",
    "TaskState",
    "WorkflowStatus",
    "Hooks",
    "run_workflow",
    "run_workflow_from_file",
    "resume_run",
    "load_workflow_from_json",
    "get_workflow_status",
    "get_run_status",
    "get_workflow_history",
    "get_run_history",
    "list_runs",
    "get_connection",
    "OrchestrationError",
    "WorkflowDefinitionError",
    "WorkflowValidationError",
    "PersistenceError",
]
