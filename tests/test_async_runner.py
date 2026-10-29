"""Tests for the native asyncio workflow runner."""

import asyncio
import time
from pathlib import Path

import pytest

from orchestration_engine import (
    Hooks,
    RetryPolicy,
    Task,
    TaskResult,
    Workflow,
    WorkflowBuilder,
    WorkflowStatus,
    WorkflowValidationError,
    get_connection,
    get_run_history,
    get_run_status,
    run_workflow_async,
)


def test_async_workflow_basic(tmp_path: Path) -> None:
    async def _test() -> None:
        db_file = str(tmp_path / "async_basic.db")
        conn = get_connection(db_file)

        wf = (
            WorkflowBuilder("async-pipeline")
            .name("Async Pipeline")
            .task("fetch", name="Fetch Async Data")
            .task("process", name="Process Async Data", dependencies=["fetch"])
            .build()
        )

        async def async_runner(task: Task) -> TaskResult:
            await asyncio.sleep(0.01)
            if task.task_id == "fetch":
                return TaskResult(ok=True, output={"raw": [1, 2, 3]})
            elif task.task_id == "process":
                raw_data = task.inputs.get("fetch", {}).get("raw", [])
                return TaskResult(ok=True, output={"sum": sum(raw_data)})
            return TaskResult(ok=False, error="Unknown task")

        status = await run_workflow_async(
            wf,
            async_runner,
            conn=conn,
            run_id="run-async-1",
        )

        assert status == WorkflowStatus.SUCCEEDED
        assert get_run_status(conn, "run-async-1") == WorkflowStatus.SUCCEEDED

        history = get_run_history(conn, "run-async-1")
        task_events = [h[2] for h in history]
        assert "fetch" in task_events
        assert "process" in task_events
        conn.close()

    asyncio.run(_test())


def test_async_workflow_sync_runner() -> None:
    async def _test() -> None:
        wf = (
            WorkflowBuilder("sync-in-async")
            .task("t1")
            .task("t2", dependencies=["t1"])
            .build()
        )

        def sync_runner(task: Task) -> bool:
            return True

        status = await run_workflow_async(wf, sync_runner)
        assert status == WorkflowStatus.SUCCEEDED

    asyncio.run(_test())


def test_async_workflow_concurrency() -> None:
    async def _test() -> None:
        builder = WorkflowBuilder("fanout-pipeline")
        task_count = 15
        for i in range(task_count):
            builder.task(f"task_{i}")
        wf = builder.build()

        active_count = 0
        max_observed_active = 0

        async def concurrent_runner(task: Task) -> bool:
            nonlocal active_count, max_observed_active
            active_count += 1
            if active_count > max_observed_active:
                max_observed_active = active_count
            await asyncio.sleep(0.03)
            active_count -= 1
            return True

        start_time = time.perf_counter()
        status = await run_workflow_async(
            wf,
            concurrent_runner,
            max_concurrency=10,
        )
        elapsed = time.perf_counter() - start_time

        assert status == WorkflowStatus.SUCCEEDED
        # With max_concurrency 10, multiple tasks ran in parallel
        assert max_observed_active >= 5
        # Total time should be well below sequential time (15 * 0.03 = 0.45s)
        assert elapsed < 0.25

    asyncio.run(_test())


def test_async_workflow_task_timeout() -> None:
    async def _test() -> None:
        wf = (
            WorkflowBuilder("timeout-pipeline")
            .task("slow_task", timeout_seconds=0.04)
            .build()
        )

        async def slow_runner(task: Task) -> bool:
            await asyncio.sleep(0.5)
            return True

        status = await run_workflow_async(wf, slow_runner)
        assert status == WorkflowStatus.FAILED
        assert "TimeoutError" in (wf.tasks[0].last_error or "")

    asyncio.run(_test())


def test_async_workflow_retry_policy() -> None:
    async def _test() -> None:
        wf = (
            WorkflowBuilder("retry-pipeline")
            .task(
                "flaky_task",
                retry_policy=RetryPolicy(max_attempts=3, delay_seconds=0.02),
            )
            .build()
        )

        attempts = 0

        async def flaky_runner(task: Task) -> TaskResult:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                return TaskResult(ok=False, error="Temporary failure")
            return TaskResult(ok=True, output={"status": "recovered"})

        status = await run_workflow_async(wf, flaky_runner)
        assert status == WorkflowStatus.SUCCEEDED
        assert attempts == 2
        assert wf.tasks[0].attempt_count == 2

    asyncio.run(_test())


def test_async_workflow_hooks() -> None:
    async def _test() -> None:
        wf = (
            WorkflowBuilder("hooks-pipeline")
            .task("step1")
            .build()
        )

        started = []
        succeeded = []
        completed = []

        hooks = Hooks(
            on_task_start=lambda t: started.append(t.task_id),
            on_task_succeeded=lambda t: succeeded.append(t.task_id),
            on_workflow_done=lambda w, s: completed.append((w.workflow_id, s)),
        )

        async def runner(task: Task) -> bool:
            return True

        status = await run_workflow_async(wf, runner, hooks=hooks)
        assert status == WorkflowStatus.SUCCEEDED
        assert started == ["step1"]
        assert succeeded == ["step1"]
        assert completed == [("hooks-pipeline", WorkflowStatus.SUCCEEDED)]

    asyncio.run(_test())


def test_async_workflow_validation_error() -> None:
    async def _test() -> None:
        # 1. Invalid DAG (cycle)
        wf_invalid = Workflow(
            workflow_id="cyclic",
            name="Cyclic",
            description="",
            tasks=[
                Task(
                    task_id="a",
                    workflow_id="cyclic",
                    name="A",
                    description="",
                    dependencies=["b"],
                    state="pending",  # type: ignore[arg-type]
                    retry_policy=RetryPolicy(1, 0.0),
                ),
                Task(
                    task_id="b",
                    workflow_id="cyclic",
                    name="B",
                    description="",
                    dependencies=["a"],
                    state="pending",  # type: ignore[arg-type]
                    retry_policy=RetryPolicy(1, 0.0),
                ),
            ],
        )

        with pytest.raises(WorkflowValidationError):
            await run_workflow_async(wf_invalid, lambda t: True)

        # 2. Invalid max_concurrency
        wf_valid = WorkflowBuilder("valid").task("x").build()
        with pytest.raises(WorkflowValidationError):
            await run_workflow_async(wf_valid, lambda t: True, max_concurrency=0)

    asyncio.run(_test())
