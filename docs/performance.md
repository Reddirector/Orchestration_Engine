# Performance & Benchmarks

This document records baseline performance metrics for `orchestration-engine`, including scheduling latency, SQLite audit log write throughput, and multi-worker concurrency scaling.

> [!NOTE]
> Benchmarks measure engine overhead and durability performance. They are not run as assertions in continuous integration. To reproduce these measurements, run:
> ```bash
> python -m benchmarks.run_all
> ```

---

## Environment Details

- **Operating System**: `Linux 7.0.0-38-generic (x86_64)`
- **Python Runtime**: `CPython 3.12.13`
- **CPU Architecture**: `24 Logical Cores (x86_64)`
- **Storage**: SSD (ext4)

---

## 1. Scheduling Overhead per Task

Measures the single-writer coordinator loop scheduling overhead and write-ahead state machine transition latency across a linear chain of 500 no-op tasks:

| Metric | Measured Value |
|---|---|
| Total Tasks | 500 |
| Total Wall-Clock Time | 0.3136 s |
| Average Latency per Task | 627.23 µs |
| Scheduling Throughput | 1,594.3 tasks / second |

**Analysis**: Average scheduling overhead per task is under 1 millisecond (~0.62ms), making coordinator overhead negligible compared to typical real-world I/O or LLM response times (100ms - 5000ms).

---

## 2. Event-Log Write Throughput

Measures append-only event-log write speed to an on-disk SQLite database configured with Write-Ahead Logging (`PRAGMA journal_mode = WAL`) and `PRAGMA synchronous = NORMAL`:

| Metric | Measured Value |
|---|---|
| Events Logged | 1,000 |
| Total Time | 0.0224 s |
| Average Write Latency | 22.36 µs |
| Write Throughput | 44,730.5 writes / second |

**Analysis**: WAL mode achieves over 44,000 durable write operations per second, confirming that SQLite write-ahead logging does not bottleneck single-node workflows.

---

## 3. Concurrency Scaling

Measures wall-clock time executing 16 independent tasks (each task sleeping for 50ms) across varying worker concurrency levels using `ThreadPoolExecutor`:

| Concurrency (`max_concurrency`) | Wall-Clock Time (s) | Effective Speedup | Scaling Efficiency |
|---|---|---|---|
| **1** | 0.8105 s | 1.00x | 100% |
| **2** | 0.4077 s | 1.99x | 99.4% |
| **4** | 0.2044 s | 3.97x | 99.1% |
| **8** | 0.1031 s | 7.86x | 98.2% |

**Analysis**: The engine exhibits near-linear speedup as `max_concurrency` scales from 1 to 8 workers, demonstrating near-zero lock contention in the coordinator dispatch loop.
