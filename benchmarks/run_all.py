"""Run all performance benchmarks and print a markdown summary table."""

from __future__ import annotations

import os
import platform
import sys

from benchmarks.concurrency_scaling import measure_concurrency_scaling
from benchmarks.event_log_throughput import measure_event_log_throughput
from benchmarks.scheduling_overhead import measure_scheduling_overhead


def run_all() -> str:
    sched = measure_scheduling_overhead(task_count=500)
    evt = measure_event_log_throughput(event_count=1000)
    conc = measure_concurrency_scaling(task_count=16, sleep_per_task=0.05)

    cpu_count = os.cpu_count() or 1
    python_ver = sys.version.split()[0]
    os_name = f"{platform.system()} {platform.release()} ({platform.machine()})"

    lines = [
        "# Performance & Benchmark Report",
        "",
        "## Environment Details",
        f"- **Operating System**: `{os_name}`",
        f"- **Python Version**: `{python_ver}`",
        f"- **Logical CPU Cores**: `{cpu_count}`",
        "",
        "## Benchmark Results",
        "",
        "### 1. Scheduling Overhead per Task",
        "Measures coordinator scheduling and state machine transition latency in a "
        "linear chain of 500 no-op tasks:",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total Tasks | {int(sched['task_count'])} |",
        f"| Total Wall-Clock Time | {sched['total_seconds']:.4f} s |",
        f"| Average Latency per Task | {sched['avg_microseconds_per_task']:.2f} µs |",
        f"| Scheduling Throughput | {sched['tasks_per_second']:.1f} tasks/s |",
        "",
        "### 2. Event-Log Write Throughput",
        "Measures append-only event-log write speed to SQLite database on disk in WAL mode:",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Events Logged | {int(evt['event_count'])} |",
        f"| Total Time | {evt['total_seconds']:.4f} s |",
        f"| Average Write Latency | {evt['avg_microseconds_per_write']:.2f} µs |",
        f"| Write Throughput | {evt['writes_per_second']:.1f} writes/s |",
        "",
        "### 3. Concurrency Scaling",
        "Measures execution time of 16 independent tasks (50ms sleep per task) across "
        "worker concurrency levels:",
        "",
        "| Concurrency (`max_concurrency`) | Wall-Clock Time (s) | Effective Speedup |",
        "|---|---|---|",
    ]

    base_dur = conc[1]
    for c, dur in sorted(conc.items()):
        speedup = base_dur / dur
        lines.append(f"| {c} | {dur:.4f} s | {speedup:.2f}x |")

    return "\n".join(lines)


if __name__ == "__main__":
    print(run_all())
