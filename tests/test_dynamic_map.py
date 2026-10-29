"""Unit tests for Dynamic Task Mapping and Fan-Out / Fan-In."""

from __future__ import annotations

import asyncio
import sqlite3
import time

from orchestration_engine.async_runner import run_workflow_async
from orchestration_engine.builder import WorkflowBuilder
from orchestration_engine.dynamic_map import fan_in_task, map_tasks
from orchestration_engine.models import Task, TaskResult
from orchestration_engine.runner import run_workflow


def test_map_tasks_and_fan_in_units() -> None:
    items = ["item_a", "item_b", "item_c"]
    mapped = map_tasks(
        base_task_id="chunk",
        items=items,
        name_prefix="Process Chunk",
        dependencies=["init"],
    )

    assert len(mapped) == 3
    assert mapped[0].task_id == "chunk_0"
    assert mapped[0].dependencies == ["init"]
    assert mapped[0].inputs == {"item": "item_a", "index": 0, "total": 3}
    assert mapped[2].inputs == {"item": "item_c", "index": 2, "total": 3}

    reducer = fan_in_task(
        task_id="gather",
        mapped_tasks=mapped,
        name="Gather All",
    )
    assert reducer.task_id == "gather"
    assert reducer.dependencies == ["chunk_0", "chunk_1", "chunk_2"]


def test_workflow_builder_mapped_tasks_sync(conn: sqlite3.Connection) -> None:
    corpus = ["doc1", "doc2", "doc3", "doc4"]

    wf = (
        WorkflowBuilder("fanout-pipeline")
        .task("setup", name="Initialize Pipeline")
        .map_tasks(
            base_task_id="embed",
            items=corpus,
            dependencies=["setup"],
            reducer_task_id="aggregate",
            reducer_name="Aggregate Embeddings",
        )
        .build()
    )

    assert len(wf.tasks) == 1 + 4 + 1  # setup + 4 mapped + aggregate
    processed_items: list[str] = []

    def runner(task: Task) -> TaskResult:
        if task.task_id == "setup":
            return TaskResult(ok=True, output={"status": "ready"})
        if task.task_id.startswith("embed_"):
            item = task.inputs.get("item", "")
            processed_items.append(item)
            return TaskResult(ok=True, output={"vector_len": len(item)})
        # Aggregate
        return TaskResult(ok=True, output={"total_embedded": len(processed_items)})

    run_id = run_workflow(
        workflow=wf,
        task_states={},
        time_source=time.time,
        task_runner=runner,
        conn=conn,
        max_concurrency=2,
    )

    assert run_id is not None
    assert len(processed_items) == 4
    assert sorted(processed_items) == sorted(corpus)


def test_workflow_builder_mapped_tasks_async(conn: sqlite3.Connection) -> None:
    items = [10, 20, 30]

    wf = (
        WorkflowBuilder("async-fanout")
        .map_tasks(
            base_task_id="square",
            items=items,
            reducer_task_id="sum",
        )
        .build()
    )

    async def _test() -> None:
        async def runner(task: Task) -> TaskResult:
            await asyncio.sleep(0.005)
            if task.task_id.startswith("square_"):
                val = task.inputs.get("item", 0)
                return TaskResult(ok=True, output=val * val)
            return TaskResult(ok=True, output="summed")

        res = await run_workflow_async(
            workflow=wf,
            task_runner=runner,
            conn=conn,
            max_concurrency=3,
        )
        assert res.value == "succeeded"

    asyncio.run(_test())
