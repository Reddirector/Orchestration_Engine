"""
Task Mutation Interceptors & Middleware Pipeline for Orchestration Engine.

Provides an onion-style, chainable middleware/interceptor execution stack for tasks,
enabling cross-cutting capabilities such as secret masking, execution timing, and audit logs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from orchestration_engine.models import Task, TaskResult


@dataclass
class TaskExecutionContext:
    """Carries execution state, metadata, and task payload across the middleware chain."""

    task: Task
    run_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float | None = None
    end_time: float | None = None
    attempt: int = 1


Middleware = Callable[
    [TaskExecutionContext, Callable[[TaskExecutionContext], TaskResult]],
    TaskResult,
]


class MiddlewarePipeline:
    """Chainable execution pipeline executing middlewares in FIFO order around task runners."""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = list(middlewares or [])

    def use(self, middleware: Middleware) -> MiddlewarePipeline:
        """Register a middleware at the end of the pipeline. Returns self for fluent chaining."""
        self._middlewares.append(middleware)
        return self

    def execute(
        self,
        context: TaskExecutionContext,
        handler: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        """Execute the full middleware chain terminating at the core handler."""

        def build_chain(
            index: int,
        ) -> Callable[[TaskExecutionContext], TaskResult]:
            if index >= len(self._middlewares):
                return handler

            curr_mw = self._middlewares[index]
            next_step = build_chain(index + 1)

            def step(ctx: TaskExecutionContext) -> TaskResult:
                return curr_mw(ctx, next_step)

            return step

        entrypoint = build_chain(0)
        return entrypoint(context)

    def wrap_runner(
        self,
        runner: Callable[[Task], TaskResult],
        run_id: str = "",
    ) -> Callable[[Task], TaskResult]:
        """Wrap a standard Task -> TaskResult callable with this middleware pipeline."""

        def wrapped(task: Task) -> TaskResult:
            actual_run_id = getattr(task, "_run_id", getattr(task, "run_id", run_id))
            ctx = TaskExecutionContext(
                task=task,
                run_id=actual_run_id,
                start_time=time.time(),
            )

            def core_handler(c: TaskExecutionContext) -> TaskResult:
                return runner(c.task)

            return self.execute(ctx, core_handler)

        return wrapped


def _mask_dict(data: Any, secret_keys: set[str], mask_value: str) -> Any:
    """Recursively redact keys matching secret patterns in dict structures."""
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for k, v in data.items():
            k_lower = k.lower()
            if k_lower in secret_keys or any(
                s in k_lower for s in ("token", "secret", "password", "key")
            ):
                masked[k] = mask_value
            else:
                masked[k] = _mask_dict(v, secret_keys, mask_value)
        return masked
    if isinstance(data, list):
        return [_mask_dict(item, secret_keys, mask_value) for item in data]
    return data


def secret_masking_middleware(
    secret_keys: set[str] | None = None,
    mask_value: str = "***REDACTED***",
) -> Middleware:
    """Middleware that recursively masks sensitive credentials in task inputs and outputs."""
    keys = {k.lower() for k in (secret_keys or {"api_key", "password", "token", "secret"})}

    def middleware(
        ctx: TaskExecutionContext,
        next_handler: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        # Mask inputs in-place
        if ctx.task.inputs:
            ctx.task.inputs = _mask_dict(ctx.task.inputs, keys, mask_value)

        result = next_handler(ctx)

        # Mask outputs if dict/list
        if result.output:
            masked_output = _mask_dict(result.output, keys, mask_value)
            return TaskResult(ok=result.ok, output=masked_output, error=result.error)

        return result

    return middleware


def execution_timer_middleware(
    metric_collector: Callable[[str, float], None] | None = None,
) -> Middleware:
    """Middleware recording precise execution duration in milliseconds into context metadata."""

    def middleware(
        ctx: TaskExecutionContext,
        next_handler: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        t0 = time.perf_counter()
        try:
            return next_handler(ctx)
        finally:
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 3)
            ctx.metadata["duration_ms"] = duration_ms
            if metric_collector:
                metric_collector(ctx.task.task_id, duration_ms)

    return middleware


def audit_logging_middleware(
    log_sink: list[dict[str, Any]],
) -> Middleware:
    """Middleware appending structured start and finish audit records to a sink."""

    def middleware(
        ctx: TaskExecutionContext,
        next_handler: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        start_entry = {
            "task_id": ctx.task.task_id,
            "run_id": ctx.run_id,
            "phase": "START",
            "timestamp": time.time(),
        }
        log_sink.append(start_entry)

        result = next_handler(ctx)

        end_entry = {
            "task_id": ctx.task.task_id,
            "run_id": ctx.run_id,
            "phase": "END",
            "ok": result.ok,
            "timestamp": time.time(),
        }
        log_sink.append(end_entry)
        return result

    return middleware
