"""
Ergonomic decorator API for authoring workflows and tasks in Python.

Provides `@task` and `@workflow` decorators that compile directly into
standard Workflow and Task objects with zero external runtime dependencies.
"""

from __future__ import annotations

import functools
import inspect
import sqlite3
import time
from collections.abc import Callable, Coroutine
from typing import Any, overload

from orchestration_engine.async_runner import run_workflow_async
from orchestration_engine.models import (
    Hooks,
    RetryPolicy,
    Task,
    TaskResult,
    TaskState,
    Workflow,
    WorkflowStatus,
)
from orchestration_engine.persistence import get_connection
from orchestration_engine.runner import run_workflow


class TaskWrapper:
    """Wraps a Python function into an orchestration task specification."""

    def __init__(
        self,
        func: Callable[..., Any],
        task_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        dependencies: list[str] | None = None,
        max_attempts: int = 1,
        delay_seconds: float = 1.0,
        timeout_seconds: float | None = 30.0,
    ) -> None:
        self.func = func
        self.task_id = task_id or func.__name__
        self.name = name or func.__name__.replace("_", " ").title()
        self.description = description or (func.__doc__ or "").strip()
        self.dependencies = list(dependencies or [])
        self.max_attempts = max_attempts
        self.delay_seconds = delay_seconds
        self.timeout_seconds = timeout_seconds
        functools.update_wrapper(self, func)

    def to_task(self, workflow_id: str = "") -> Task:
        """Convert wrapper to standard Task dataclass instance."""
        return Task(
            task_id=self.task_id,
            workflow_id=workflow_id,
            name=self.name,
            description=self.description,
            dependencies=list(self.dependencies),
            state=TaskState.PENDING,
            retry_policy=RetryPolicy(
                max_attempts=self.max_attempts,
                delay_seconds=self.delay_seconds,
            ),
            attempt_count=0,
            next_retry_at=None,
            timeout_seconds=self.timeout_seconds,
        )

    def execute_for_engine(
        self, task: Task
    ) -> bool | TaskResult | Coroutine[Any, Any, bool | TaskResult]:
        """Execute the wrapped function in engine context, adapting arguments and return value."""
        sig = inspect.signature(self.func)
        params = list(sig.parameters.values())

        if len(params) == 0:
            call_res = self.func()
        elif len(params) == 1 and params[0].name in ("inputs", "data"):
            call_res = self.func(task.inputs)
        else:
            call_res = self.func(task)

        if inspect.isawaitable(call_res):
            async def _adapt_async() -> bool | TaskResult:
                res = await call_res
                return _adapt_result(res)
            return _adapt_async()

        return _adapt_result(call_res)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Calling the task wrapper standalone runs the underlying function directly."""
        return self.func(*args, **kwargs)


def _adapt_result(res: Any) -> bool | TaskResult:
    if isinstance(res, TaskResult):
        return res
    if isinstance(res, bool):
        return res
    # Any other returned data is treated as successful output
    return TaskResult(ok=True, output=res)


@overload
def task[F: Callable[..., Any]](func: F) -> TaskWrapper: ...


@overload
def task[F: Callable[..., Any]](
    func: None = None,
    *,
    task_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    dependencies: list[str | TaskWrapper] | None = None,
    max_attempts: int = 1,
    delay_seconds: float = 1.0,
    timeout_seconds: float | None = 30.0,
) -> Callable[[F], TaskWrapper]: ...


def task(
    func: Callable[..., Any] | None = None,
    *,
    task_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    dependencies: list[str | TaskWrapper] | None = None,
    max_attempts: int = 1,
    delay_seconds: float = 1.0,
    timeout_seconds: float | None = 30.0,
) -> Any:
    """
    Decorator for defining workflow tasks.

    Can be used with or without arguments:
        @task
        def step1():
            return {"data": 123}

        @task(task_id="step2", dependencies=["step1"], max_attempts=3)
        def step2(task: Task):
            ...
    """
    dep_ids: list[str] = []
    if dependencies:
        for d in dependencies:
            if isinstance(d, TaskWrapper):
                dep_ids.append(d.task_id)
            elif isinstance(d, str):
                dep_ids.append(d)

    def decorator(fn: Callable[..., Any]) -> TaskWrapper:
        return TaskWrapper(
            func=fn,
            task_id=task_id,
            name=name,
            description=description,
            dependencies=dep_ids,
            max_attempts=max_attempts,
            delay_seconds=delay_seconds,
            timeout_seconds=timeout_seconds,
        )

    if func is not None:
        return decorator(func)
    return decorator


class WorkflowDefinition:
    """Compiled workflow definition produced by the @workflow decorator."""

    def __init__(
        self,
        workflow: Workflow,
        task_registry: dict[str, TaskWrapper],
    ) -> None:
        self.workflow = workflow
        self.task_registry = task_registry

    def _task_runner(self, task_obj: Task) -> Any:
        wrapper = self.task_registry.get(task_obj.task_id)
        if not wrapper:
            return False
        return wrapper.execute_for_engine(task_obj)

    def run(
        self,
        conn: sqlite3.Connection | None = None,
        db_path: str | None = None,
        max_concurrency: int = 1,
        executor: str = "thread",
        hooks: Hooks | None = None,
        time_source: Callable[[], float] = time.time,
        run_id: str | None = None,
    ) -> str:
        """Execute the workflow synchronously using run_workflow."""
        close_on_exit = False
        if conn is None:
            conn = get_connection(db_path or ":memory:")
            close_on_exit = True

        try:
            return run_workflow(
                self.workflow,
                task_states={},
                time_source=time_source,
                task_runner=self._task_runner,
                conn=conn,
                max_concurrency=max_concurrency,
                executor=executor,  # type: ignore[arg-type]
                hooks=hooks,
                run_id=run_id,
            )
        finally:
            if close_on_exit:
                conn.close()

    async def run_async(
        self,
        conn: sqlite3.Connection | None = None,
        db_path: str | None = None,
        max_concurrency: int = 100,
        hooks: Hooks | None = None,
        time_source: Callable[[], float] = time.time,
        run_id: str | None = None,
    ) -> WorkflowStatus:
        """Execute the workflow asynchronously using run_workflow_async."""
        return await run_workflow_async(
            self.workflow,
            task_runner=self._task_runner,
            conn=conn,
            db_path=db_path,
            max_concurrency=max_concurrency,
            hooks=hooks,
            time_source=time_source,
            run_id=run_id,
        )

    def __call__(self) -> Workflow:
        """Calling the definition returns the underlying Workflow DAG."""
        return self.workflow


@overload
def workflow[WF: Callable[..., Any]](func: WF) -> WorkflowDefinition: ...


@overload
def workflow[WF: Callable[..., Any]](
    func: None = None,
    *,
    workflow_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    default_timeout_seconds: float | None = None,
) -> Callable[[WF], WorkflowDefinition]: ...


def workflow(
    func: Callable[..., Any] | None = None,
    *,
    workflow_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    default_timeout_seconds: float | None = None,
) -> Any:
    """
    Decorator for defining workflows.

    The decorated function should return an iterable of task functions or wrappers.

    Example:
        @workflow(workflow_id="etl-pipeline")
        def etl():
            return [extract, transform, load]

        run_id = etl.run(db_path="orchestration.db")
    """
    def decorator(fn: Callable[..., Any]) -> WorkflowDefinition:
        wf_id = workflow_id or fn.__name__
        wf_name = name or fn.__name__.replace("_", " ").title()
        wf_desc = description or (fn.__doc__ or "").strip()

        # Call function to collect tasks
        result = fn()
        tasks_list: list[TaskWrapper] = []
        if isinstance(result, (list, tuple, set)):
            for item in result:
                if isinstance(item, TaskWrapper):
                    tasks_list.append(item)
                elif callable(item) and hasattr(item, "__wrapped__"):
                    tasks_list.append(TaskWrapper(item))
                elif callable(item):
                    tasks_list.append(TaskWrapper(item))

        task_models: list[Task] = []
        task_registry: dict[str, TaskWrapper] = {}
        for tw in tasks_list:
            task_models.append(tw.to_task(workflow_id=wf_id))
            task_registry[tw.task_id] = tw

        wf_obj = Workflow(
            workflow_id=wf_id,
            name=wf_name,
            description=wf_desc,
            tasks=task_models,
            default_timeout_seconds=default_timeout_seconds,
        )

        return WorkflowDefinition(wf_obj, task_registry)

    if func is not None:
        return decorator(func)
    return decorator
