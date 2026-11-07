"""
Unit tests for Task Mutation Interceptors & Middleware Pipeline.
"""

from collections.abc import Callable
from typing import Any

from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.middleware import (
    MiddlewarePipeline,
    TaskExecutionContext,
    audit_logging_middleware,
    execution_timer_middleware,
    secret_masking_middleware,
)
from orchestration_engine.models import Task, TaskResult


def test_middleware_pipeline_onion_flow() -> None:
    order: list[str] = []

    def mw1(
        ctx: TaskExecutionContext,
        nxt: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        order.append("mw1_before")
        res = nxt(ctx)
        order.append("mw1_after")
        return res

    def mw2(
        ctx: TaskExecutionContext,
        nxt: Callable[[TaskExecutionContext], TaskResult],
    ) -> TaskResult:
        order.append("mw2_before")
        res = nxt(ctx)
        order.append("mw2_after")
        return res

    pipeline = MiddlewarePipeline().use(mw1).use(mw2)
    task = WorkflowBuilder("wf").task("t1", name="Task 1").build().tasks[0]

    def runner(t: Task) -> TaskResult:
        order.append("runner")
        return TaskResult(ok=True, output={"msg": "success"})

    wrapped = pipeline.wrap_runner(runner)
    result = wrapped(task)

    assert result.ok is True
    assert order == ["mw1_before", "mw2_before", "runner", "mw2_after", "mw1_after"]


def test_secret_masking_middleware() -> None:
    pipeline = MiddlewarePipeline().use(secret_masking_middleware())
    task = WorkflowBuilder("wf").task("t_secret", name="Sensitive Task").build().tasks[0]
    task.inputs = {
        "user": "alice",
        "api_key": "sk_live_99999999",
        "nested": {"db_password": "supersecretpassword"},
    }

    def runner(t: Task) -> TaskResult:
        # Verify inputs were masked before runner received them
        assert t.inputs["api_key"] == "***REDACTED***"
        assert t.inputs["nested"]["db_password"] == "***REDACTED***"
        return TaskResult(
            ok=True,
            output={
                "session_token": "token_abc123",
                "normal_field": "visible",
            },
        )

    wrapped = pipeline.wrap_runner(runner)
    result = wrapped(task)

    assert result.ok is True
    assert result.output is not None
    assert result.output["session_token"] == "***REDACTED***"
    assert result.output["normal_field"] == "visible"


def test_timer_and_audit_logging_middleware() -> None:
    audit_records: list[dict[str, Any]] = []
    collected_metrics: dict[str, float] = {}

    def metric_sink(tid: str, duration_ms: float) -> None:
        collected_metrics[tid] = duration_ms

    pipeline = (
        MiddlewarePipeline()
        .use(audit_logging_middleware(audit_records))
        .use(execution_timer_middleware(metric_sink))
    )

    task = WorkflowBuilder("wf").task("t_timed", name="Timed Task").build().tasks[0]

    def runner(t: Task) -> TaskResult:
        return TaskResult(ok=True, output={"val": 42})

    wrapped = pipeline.wrap_runner(runner, run_id="run_test_audit")
    res = wrapped(task)

    assert res.ok is True
    assert "t_timed" in collected_metrics
    assert collected_metrics["t_timed"] >= 0.0

    assert len(audit_records) == 2
    assert audit_records[0]["task_id"] == "t_timed"
    assert audit_records[0]["phase"] == "START"
    assert audit_records[1]["task_id"] == "t_timed"
    assert audit_records[1]["phase"] == "END"
    assert audit_records[1]["ok"] is True
