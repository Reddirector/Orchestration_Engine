"""Example task runners for use with CLI and tests."""

from __future__ import annotations

import sys

from orchestration_engine.models import Task


def run(task: Task) -> bool:
    """Default success runner for example workflows."""
    print(f"Executing task: {task.name} ({task.task_id})", file=sys.stderr)
    return True


def failing_runner(task: Task) -> bool:
    """Runner that always fails for testing failure handling."""
    raise RuntimeError(f"Task '{task.task_id}' intentionally failed")


NOT_A_CALLABLE = "not_callable"
