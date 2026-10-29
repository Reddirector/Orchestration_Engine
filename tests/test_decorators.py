"""Tests for the ergonomic Python decorator API (@task and @workflow)."""

import asyncio
from pathlib import Path
from typing import Any

from orchestration_engine import (
    Task,
    TaskResult,
    WorkflowStatus,
    get_connection,
    get_run_status,
    task,
    workflow,
)
from orchestration_engine.persistence import get_task_outputs


def test_task_direct_call() -> None:
    @task
    def compute(a: int, b: int) -> int:
        return a + b

    assert compute(2, 3) == 5
    assert compute.task_id == "compute"
    assert compute.name == "Compute"


def test_workflow_sync_run(tmp_path: Path) -> None:
    db_file = str(tmp_path / "decorator_test.db")
    conn = get_connection(db_file)

    @task(max_attempts=2)
    def fetch_records() -> list[int]:
        return [10, 20, 30]

    @task(dependencies=[fetch_records])
    def sum_records(task: Task) -> int:
        records: list[int] = task.inputs["fetch_records"]
        return sum(records)

    @workflow(workflow_id="math-pipeline")
    def math_flow() -> list[Any]:
        return [fetch_records, sum_records]

    # Verify calling workflow definition returns Workflow model
    wf_model = math_flow()
    assert wf_model.workflow_id == "math-pipeline"
    assert len(wf_model.tasks) == 2

    # Execute workflow synchronously
    run_id = math_flow.run(conn=conn)
    assert run_id is not None
    assert get_run_status(conn, run_id) == WorkflowStatus.SUCCEEDED

    outputs = get_task_outputs(conn, run_id)
    assert outputs["fetch_records"] == [10, 20, 30]
    assert outputs["sum_records"] == 60
    conn.close()


def test_workflow_async_run() -> None:
    async def _test() -> None:
        @task
        async def fetch_async() -> TaskResult:
            await asyncio.sleep(0.01)
            return TaskResult(ok=True, output={"status": "fetched"})

        @task(dependencies=["fetch_async"])
        async def process_async(task: Task) -> TaskResult:
            status = task.inputs["fetch_async"]["status"]
            return TaskResult(ok=True, output=f"done-{status}")

        @workflow(workflow_id="async-dec-wf")
        def async_flow() -> list[Any]:
            return [fetch_async, process_async]

        status = await async_flow.run_async()
        assert status == WorkflowStatus.SUCCEEDED

    asyncio.run(_test())


def test_task_inputs_named_parameter() -> None:
    @task
    def produce() -> dict[str, int]:
        return {"value": 42}

    @task(dependencies=["produce"])
    def consume(inputs: dict[str, Any]) -> int:
        return int(inputs["produce"]["value"]) * 2

    @workflow(workflow_id="inputs-wf")
    def pipeline() -> list[Any]:
        return [produce, consume]

    run_id = pipeline.run()
    assert run_id is not None
