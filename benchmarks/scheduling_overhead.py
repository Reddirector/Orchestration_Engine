"""Benchmark: Scheduling overhead per task."""

from __future__ import annotations

import time

from orchestration_engine import (
    WorkflowBuilder,
    get_connection,
    run_workflow,
)


def measure_scheduling_overhead(task_count: int = 500) -> dict[str, float]:
    """Measure scheduling overhead per task in a linear chain."""
    builder = WorkflowBuilder("overhead-wf", "Scheduling Overhead Benchmark")
    for i in range(task_count):
        dep = [f"t{i-1}"] if i > 0 else []
        builder.task(f"t{i}", name=f"Task {i}", dependencies=dep)
    workflow = builder.build()

    conn = get_connection(":memory:")

    start = time.perf_counter()
    run_workflow(
        workflow=workflow,
        task_states={},
        time_source=time.time,
        task_runner=lambda t: True,
        conn=conn,
        max_concurrency=1,
    )
    duration = time.perf_counter() - start

    avg_micros = (duration / task_count) * 1_000_000
    tasks_per_sec = task_count / duration

    return {
        "task_count": float(task_count),
        "total_seconds": duration,
        "avg_microseconds_per_task": avg_micros,
        "tasks_per_second": tasks_per_sec,
    }


if __name__ == "__main__":
    res = measure_scheduling_overhead()
    print(f"Tasks: {int(res['task_count'])}")
    print(f"Total time: {res['total_seconds']:.4f}s")
    print(f"Average overhead: {res['avg_microseconds_per_task']:.2f} µs/task")
    print(f"Throughput: {res['tasks_per_second']:.1f} tasks/sec")
