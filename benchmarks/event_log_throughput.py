"""Benchmark: Event log write throughput."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from orchestration_engine.persistence import get_connection, log_task_event


def measure_event_log_throughput(event_count: int = 1000) -> dict[str, float]:
    """Measure raw state transition audit write throughput on disk."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "bench.db")
        conn = get_connection(db_path)

        start = time.perf_counter()
        now = time.time()
        for i in range(event_count):
            log_task_event(
                conn,
                workflow_id="bench-wf",
                task_id=f"t{i}",
                old_state="pending",
                new_state="running",
                timestamp=now,
                attempt_count=1,
                run_id="run-bench",
            )
        duration = time.perf_counter() - start

        writes_per_sec = event_count / duration
        avg_micros = (duration / event_count) * 1_000_000

        return {
            "event_count": float(event_count),
            "total_seconds": duration,
            "writes_per_second": writes_per_sec,
            "avg_microseconds_per_write": avg_micros,
        }


if __name__ == "__main__":
    res = measure_event_log_throughput()
    print(f"Events written: {int(res['event_count'])}")
    print(f"Total time: {res['total_seconds']:.4f}s")
    print(f"Throughput: {res['writes_per_second']:.1f} events/sec")
    print(f"Average write latency: {res['avg_microseconds_per_write']:.2f} µs/write")
