"""Benchmark: Concurrency scaling comparison."""

from __future__ import annotations

import time

from orchestration_engine import (
    WorkflowBuilder,
    get_connection,
    run_workflow,
)


def measure_concurrency_scaling(
    task_count: int = 16,
    sleep_per_task: float = 0.05,
    concurrency_levels: tuple[int, ...] = (1, 2, 4, 8),
) -> dict[int, float]:
    """Measure wall-clock time executing parallel tasks across concurrency levels."""
    results: dict[int, float] = {}

    for conc in concurrency_levels:
        builder = WorkflowBuilder(f"concurrency-wf-{conc}", "Concurrency Scaling Benchmark")
        for i in range(task_count):
            builder.task(f"t{i}", name=f"Parallel Task {i}")
        workflow = builder.build()

        conn = get_connection(":memory:")
        start = time.perf_counter()
        run_workflow(
            workflow=workflow,
            task_states={},
            time_source=time.time,
            task_runner=lambda t: time.sleep(sleep_per_task) or True,
            conn=conn,
            max_concurrency=conc,
        )
        duration = time.perf_counter() - start
        results[conc] = duration

    return results


if __name__ == "__main__":
    res = measure_concurrency_scaling()
    print("Concurrency Scaling (16 tasks, 50ms each):")
    for conc, dur in res.items():
        speedup = res[1] / dur
        print(f"  Concurrency {conc}: {dur:.4f}s (speedup: {speedup:.2f}x)")
